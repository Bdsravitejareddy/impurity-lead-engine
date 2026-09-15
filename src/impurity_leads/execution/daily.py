"""Durable daily stage graph; adapters and lead semantics remain synchronous."""
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import os
import signal
import threading
import time
from uuid import uuid4

from impurity_leads.contacts.models import RankedContact
from impurity_leads.execution.crawl import CrawlHandlers
from impurity_leads.execution.progress import Reporter
from impurity_leads.execution.retry import DatabaseUnavailable
from impurity_leads.execution.runner import Runner
from impurity_leads.execution.tasks import STAGES, VERSION, behavior_version, fingerprint, task
from impurity_leads.export import export_csv, export_xlsx
from impurity_leads.models import SourceRecord, Signal, Opportunity
from impurity_leads.normalize import normalize_company_name
from impurity_leads.pipeline import process_records_with_candidates
from impurity_leads.seeds import load_company_seeds
from impurity_leads.storage.memory import MemoryLeadStore
from impurity_leads.storage.supabase_store import SupabaseLeadStore
from impurity_leads.storage.task_store import create_task_store


class RowCollector:
    """Reuse production serializers without issuing intermediate DB writes."""
    def __init__(self): self.rows=[]
    def table(self,name):
        collector=self
        class Table:
            def upsert(self,row,on_conflict):
                collector.rows.append({'table':name,'row':row,'on_conflict':on_conflict})
                return self
            def execute(self): return None
        return Table()


def publication_rows(signals, opportunities, contact_map, candidates=()):
    collector=RowCollector();store=SupabaseLeadStore(collector)
    for item in signals:store.save_signal(item)
    for candidate in candidates:store.save_candidate(candidate)
    for item in opportunities:
        store.save_opportunity(item)
        for contact in contact_map.get((item.company_name,item.molecule_name),[]):
            store.save_contact(item.company_name,contact)
            store.link_opportunity_contact(item,contact)
    return collector.rows


def collected_records(rows):
    """Rebuild records in the original structured-then-seeded deterministic order."""
    records = []
    structured = sorted((r for r in rows if r.get('stage') == 'structured_sources'),
                        key=lambda r: r.get('task_key', ''))
    companies = sorted((r for r in rows if r.get('stage') == 'company_crawling'),
                       key=lambda r: r.get('task_key', ''))
    for row in structured:
        payload = row.get('result_json') or {}
        records.extend(SourceRecord.model_validate(item) for item in payload.get('records', []))
    company_items = []
    for row in companies:
        payload = row.get('result_json') or {}
        items = payload.get('records', [])
        indexes = payload.get('record_seed_indexes') or [0] * len(items)
        company_items.extend(zip(indexes, range(len(company_items), len(company_items) + len(items)), items))
    company_items.sort(key=lambda item: (item[0], item[1]))
    records.extend(SourceRecord.model_validate(item) for _, _, item in company_items)
    return records


def write_exports(directory,run_id,opportunities,contacts):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    paths=[]
    for suffix,exporter in [('csv',export_csv),('xlsx',export_xlsx)]:
        final=directory/f'opportunities-{run_id}.{suffix}'
        temporary=directory/f'.opportunities-{run_id}-{uuid4().hex}.{suffix}'
        try:
            exporter(opportunities,temporary,contacts)
            os.replace(temporary,final)
        finally:
            temporary.unlink(missing_ok=True)
        paths.append(str(final))
    return paths


def execute_run(store,settings,seeds,output_dir,*,workers=6,reporter=None,client_factory=None,stop=None):
    started=time.monotonic()
    runner=Runner(store,settings,workers,stop=stop,reporter=reporter)
    handlers=CrawlHandlers(settings,client_factory=client_factory,reporter=reporter)
    grouped=defaultdict(list)
    for seed in seeds:grouped[seed.domain].append(asdict(seed))
    initial=[task('source:clinical_trials',STAGES[0],identifier='clinical_trials'),task('source:fda',STAGES[0],identifier='fda')]
    initial.extend(task(f'company:{i:06}:{domain}',STAGES[1],identifier=items[0]['company_name'],domain=domain,checkpoint={'seeds':items}) for i,(domain,items) in enumerate(grouped.items()))
    initial += [task('process:all',STAGES[2]),task('persist:all',STAGES[4]),task('export:all',STAGES[5])]
    store.plan(initial)
    metrics=dict(store.run.get('metrics_json') or {})
    timings=dict(metrics.get('stage_seconds') or {})
    base_elapsed=metrics.get('active_elapsed_seconds',0)
    def stage(name,handler):
        store.finish('running',name,metrics)
        stage_start=time.monotonic()
        complete=runner.run_stage(name,handler)
        timings[name]=timings.get(name,0)+time.monotonic()-stage_start
        metrics.update(stage_seconds=timings,active_elapsed_seconds=base_elapsed+time.monotonic()-started)
        if not complete:
            store.finish('paused',name,metrics)
        return complete
    def outputs(stage_name):
        return [r for r in store.tasks() if r['stage']==stage_name]
    if not stage(STAGES[0],handlers.structured):return 130
    if not stage(STAGES[1],handlers.company):return 130
    def process(ctx):
        records=[]
        records.extend(collected_records(store.tasks()))
        memory=MemoryLeadStore()
        opportunities, candidates = process_records_with_candidates(records,memory)
        candidate_payload = [
            {**candidate, 'last_signal_at': candidate['last_signal_at'].isoformat() if candidate.get('last_signal_at') else None}
            for candidate in candidates
        ]
        return {'signals':[s.model_dump(mode='json') for s in memory.signals],
                'opportunities':[o.model_dump(mode='json') for o in opportunities],
                'candidates': candidate_payload, 'records_seen':len(records)}
    if not stage(STAGES[2],process):return 130
    processing=outputs(STAGES[2])[0]
    if processing['status']!='completed':
        store.finish('failed',STAGES[2],metrics);return 1
    signals=[Signal.model_validate(s) for s in processing['result_json']['signals']]
    opportunities=[Opportunity.model_validate(o) for o in processing['result_json']['opportunities']]
    candidates=processing['result_json'].get('candidates', [])
    unqualified_count=sum(1 for candidate in candidates if not candidate.get('priority'))
    qualified_count=sum(1 for candidate in candidates if candidate.get('priority'))
    metrics.update(signals=len(signals),candidates=len(candidates),qualified=qualified_count,records=processing['result_json']['records_seen'],
        signals_discovered=len(signals), candidates_scored=len(candidates), new_candidate_pairs=unqualified_count,
        existing_pairs_enriched=0, new_opportunities_persisted=qualified_count,
        newly_qualified=qualified_count, promoted=0, dismissed=0, unresolved=0)
    from impurity_leads.cli import select_contact_enrichment_targets
    seed_map={normalize_company_name(s.company_name):s for s in seeds}
    selected=defaultdict(list)
    for opportunity in select_contact_enrichment_targets(opportunities):
        seed=seed_map.get(normalize_company_name(opportunity.company_name))
        if seed:selected[seed.domain].append(opportunity.company_name+'|'+opportunity.molecule_name)
    store.plan([task(f'contact:{i:06}:{domain}',STAGES[3],identifier=domain,domain=domain,checkpoint={'opportunity_keys':keys}) for i,(domain,keys) in enumerate(selected.items())])
    metrics['planning_complete']=True
    store.run.setdefault('config_json',{})['planning_complete']=True
    handlers.opportunities=opportunities
    if not stage(STAGES[3],handlers.contacts):return 130
    contact_map={}
    for row in outputs(STAGES[3]):
        for item in row['result_json'].get('contacts',[]):
            contact_map[(item['company_name'],item['molecule_name'])]=[RankedContact.model_validate(c) for c in item['ranked']]
    metrics['contacts']=len({(name,c.contact.normalized_name) for (name,_),contacts in contact_map.items() for c in contacts})
    def persist(ctx):
        rows=publication_rows(signals,opportunities,contact_map,candidates)
        for index in range(ctx.checkpoint.get('index',0),len(rows),50):
            ctx.check()
            cp={'index':min(index+50,len(rows))}
            store.publish(ctx.task,rows[index:index+50],cp)
            ctx.checkpoint=cp
        return {'rows_written':len(rows)}
    if not stage(STAGES[4],persist):return 130
    if outputs(STAGES[4])[0]['status']!='completed':
        store.finish('failed',STAGES[4],metrics);return 1
    def export(ctx):
        ctx.check()
        write_exports(output_dir,store.run['id'],opportunities,contact_map)
        return {'exported':True}
    if not stage(STAGES[5],export):return 130
    export_task=outputs(STAGES[5])[0]
    if export_task['status']!='completed':
        store.finish('failed',STAGES[5],metrics);return 1
    # Export artifacts are machine-local; missing files can be regenerated.
    if not all((Path(output_dir)/f"opportunities-{store.run['id']}.{suffix}").exists() for suffix in ['csv','xlsx']):
        write_exports(output_dir,store.run['id'],opportunities,contact_map)
    rows=store.tasks()
    metrics.update(task_count=len(rows),success_count=sum(t['status']=='completed' for t in rows),
        skip_count=sum(t['status']=='skipped' for t in rows),failure_count=sum(t['status']=='permanent_failed' for t in rows),
        retries=sum(max(0,t['attempt_count']-1) for t in rows))
    store.finish('completed_with_errors' if metrics['failure_count'] else 'completed',STAGES[5],metrics)
    if reporter:reporter.render(store.run,rows)
    return 0


def run_daily(settings,root,*,workers=6,fresh=False):
    reporter=Reporter(workers=workers)
    stop=threading.Event();previous={}
    store=None
    try:
        store=create_task_store(settings)
        seeds=load_company_seeds(Path(root)/'seeds/companies.csv') if (Path(root)/'seeds/companies.csv').exists() else []
        safe=settings.model_dump(exclude={'supabase_url','supabase_secret_key','workers'})
        material={'settings':safe,'seeds':[asdict(s) for s in seeds],'sources':['clinical_trials','fda','company_site','common_crawl'],
                  'schema_version':VERSION,'behavior_version':behavior_version()}
        run=store.begin(fingerprint(material),str(uuid4()),fresh,{'schema_version':VERSION,'seed_count':len(seeds),'workers':workers,'planning_complete':False})
        reporter.emit({'event':'run_resumed' if run.get('resumed') else 'run_started','run_id':run['id'],'status':'running'})
        if run.get('resumed'):
            reporter.render(run,store.snapshot())
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT,signal.SIGTERM):
                previous[sig]=signal.signal(sig,lambda *_:stop.set())
        result=execute_run(store,settings,seeds,Path(root)/'exports',workers=workers,reporter=reporter,stop=stop)
        if result==130:reporter.emit({'event':'resume_on_next_run','run_id':run['id'],'status':'paused'})
        return result
    except DatabaseUnavailable:
        reporter.emit({'event':'run_paused','status':'paused','error':'database_unavailable'})
        return 2
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)
        reporter.close()


def status(settings):
    reporter=Reporter(interactive=False)
    try:
        store=create_task_store(settings)
        run=store.latest()
        if not run:
            reporter.emit({'event':'no_runs','status':'none'});return 0
        reporter.render(run,store.snapshot());return 0
    except DatabaseUnavailable:
        reporter.emit({'event':'status_unavailable','error':'database_unavailable'});return 2
    finally:reporter.close()


def export_run(settings, root, run_id=None):
    """Regenerate exports from completed durable outputs without crawling."""
    reporter = Reporter(interactive=False)
    try:
        store = create_task_store(settings)
        run = store.load_run(run_id)
        if not run or run.get('status') not in {'completed', 'completed_with_errors'}:
            reporter.emit({'event': 'export_rejected', 'status': 'not_completed'})
            return 1
        tasks = store.tasks()
        scoring = next((r for r in tasks if r.get('stage') == 'processing_scoring'), None)
        if not scoring:
            reporter.emit({'event': 'export_rejected', 'status': 'missing_scoring'})
            return 1
        opportunities = [Opportunity.model_validate(item) for item in scoring.get('result_json', {}).get('opportunities', [])]
        contact_map = {}
        for row in tasks:
            if row.get('stage') != 'contact_enrichment':
                continue
            for item in row.get('result_json', {}).get('contacts', []):
                contact_map[(item['company_name'], item['molecule_name'])] = [
                    RankedContact.model_validate(contact) for contact in item.get('ranked', [])
                ]
        write_exports(Path(root) / 'exports', run['id'], opportunities, contact_map)
        reporter.emit({'event': 'export_completed', 'run_id': run['id'], 'status': 'completed'})
        return 0
    except DatabaseUnavailable:
        reporter.emit({'event': 'export_paused', 'status': 'paused', 'error': 'database_unavailable'})
        return 2
    finally:
        reporter.close()
