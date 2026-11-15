export const FORBIDDEN_CONSTANTS = [
  ["const home = 'AR'", 'country code'],
  ["area.startsWith('CA')", 'country code'],
  ['const bbox = [-73.6, -55.1, -53.6, -21.8]', 'bbox literal'],
  ['map.fitBounds([[-110, 40], [-50, 55]])', 'bbox literal'],
  ["const zone = 'America/Denver'", 'IANA zone'],
  ["const zone = 'Canada/Newfoundland'", 'IANA zone'],
  ["const zone = 'UTC−3'", 'fixed UTC label'],
  ['const zone = "UTC+5:30"', 'fixed UTC label'],
  ["const LANGS = ['en', 'fr'] as const", 'language set'],
  ["const LANGUAGES = ['en']", 'language set'],
] as const;

export const DATA_DRIVEN_CONSTANTS =
  "const bbox = config.countries[0]?.bbox; const languages = config.languages; fetch('/api/config'); const contentType = 'application/json'; const unit = 'km/h';";
