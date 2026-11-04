export function neutralizeBrand(value: string | null | undefined): string {
  return (value || '')
    .replace(/\bSVAK\b/gi, 'our team')
    .replace(/(^|[.!?]\s+)(our team)\b/g, (_, prefix: string) => `${prefix}Our team`)
}
