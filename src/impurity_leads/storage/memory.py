from impurity_leads.contacts.models import RankedContact
from impurity_leads.models import Opportunity, Signal


class MemoryLeadStore:
    def __init__(self):
        self.signals: list[Signal] = []
        self.opportunities: list[Opportunity] = []
        self.contacts: list[RankedContact] = []
        self.opportunity_contacts: list[tuple[tuple[str, str], RankedContact]] = []
        self._fingerprints: set[str] = set()

    def save_signal(self, signal: Signal) -> None:
        if signal.fingerprint in self._fingerprints:
            return
        self._fingerprints.add(signal.fingerprint)
        self.signals.append(signal)

    def save_opportunity(self, opportunity: Opportunity) -> None:
        key = (opportunity.company_name.lower(), opportunity.molecule_name.lower())
        self.opportunities = [
            item
            for item in self.opportunities
            if (item.company_name.lower(), item.molecule_name.lower()) != key
        ]
        self.opportunities.append(opportunity)

    def save_contact(self, company_name: str, ranked_contact: RankedContact) -> None:
        key = (company_name.casefold(), ranked_contact.contact.normalized_name)
        self.contacts = [
            item
            for item in self.contacts
            if (item.contact.company_name.casefold(), item.contact.normalized_name) != key
        ]
        self.contacts.append(ranked_contact)

    def link_opportunity_contact(self, opportunity: Opportunity, ranked_contact: RankedContact) -> None:
        key = (opportunity.company_name.casefold(), opportunity.molecule_name.casefold())
        self.opportunity_contacts = [
            item
            for item in self.opportunity_contacts
            if not (item[0] == key and item[1].contact.normalized_name == ranked_contact.contact.normalized_name)
        ]
        self.opportunity_contacts.append((key, ranked_contact))
