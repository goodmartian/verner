import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';
import { MESSAGES } from './i18n/translate';
import { DATA_DRIVEN_CONSTANTS, FORBIDDEN_CONSTANTS } from './test/guardFixtures';

const root = process.cwd();
/** Only data fixtures may contain example geography and enabled-language lists. */
const FIXTURES = new Set([
  'src/test/configFixtures.ts',
  'src/test/calendarFixtures.ts',
  'src/test/climateFixtures.ts',
  'src/test/fireFixtures.ts',
  'src/test/weatherFixtures.ts',
  'src/test/regionFixtures.ts',
  'src/test/guardFixtures.ts',
  'e2e/fixtures.ts',
]);
// Protocols, units and scientific indices are not country identifiers.
const WORDS = new Set([
  'KB',
  'MB',
  'GET',
  'PUT',
  'UTC',
  'USD',
  'FWI',
  'IFM',
  'HDW',
  'RGB',
  'URL',
  'API',
  'GFS',
  'SSE',
  'NFD',
  'DOM',
]);

function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    return entry.isDirectory()
      ? files(path)
      : /\.(?:[cm]?[jt]sx?|css|html|json)$/.test(path)
        ? [path]
        : [];
  });
}

/** Kept public to prove the guard catches fresh examples, not only today's source. */
export function hardcodes(source: string): string[] {
  const found = new Set<string>();
  const ast = ts.createSourceFile(
    'source.tsx',
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const numeric = (node: ts.Node): boolean =>
    ts.isNumericLiteral(node) ||
    (ts.isPrefixUnaryExpression(node) &&
      (node.operator === ts.SyntaxKind.MinusToken || node.operator === ts.SyntaxKind.PlusToken) &&
      ts.isNumericLiteral(node.operand));
  const numbers = (node: ts.Node, count: number): boolean =>
    ts.isArrayLiteralExpression(node) &&
    node.elements.length === count &&
    node.elements.every(numeric);
  const visit = (node: ts.Node) => {
    if (ts.isStringLiteralLike(node)) {
      const value = node.text;
      if (/^[A-Z]{2,3}(?:-[A-Z0-9]+)?$/.test(value) && !WORDS.has(value)) found.add('country code');
      if (/^[A-Za-z_+\-/]+\/[A-Za-z_+\-/]+$/.test(value)) {
        try {
          new Intl.DateTimeFormat(undefined, { timeZone: value });
          found.add('IANA zone');
        } catch {
          /* An import, URL path, content type or unit is not an IANA zone. */
        }
      }
      if (/UTC[+\-−]\d/.test(value)) found.add('fixed UTC label');
    }
    if (ts.isArrayLiteralExpression(node)) {
      const context = node.parent.getText(ast).slice(0, 100);
      if (
        /bbox|bounds/i.test(context) &&
        (numbers(node, 4) ||
          (node.elements.length === 2 && node.elements.every((item) => numbers(item, 2))))
      )
        found.add('bbox literal');
      if (
        (node.elements.length > 1 || /LANG(?:S|UAGES)/.test(context)) &&
        node.elements.every(
          (item) =>
            ts.isStringLiteralLike(item) && Object.hasOwn(MESSAGES, item.text.split('-')[0] ?? ''),
        )
      )
        found.add('language set');
    }
    ts.forEachChild(node, visit);
  };
  visit(ast);
  return [...found];
}

describe('geography comes from config and API data', () => {
  it.each(FORBIDDEN_CONSTANTS)('rejects %s', (source, kind) => {
    expect(hardcodes(source)).toContain(kind);
  });
  it('accepts config access, API paths, units and content types', () => {
    expect(hardcodes(DATA_DRIVEN_CONSTANTS)).toEqual([]);
  });
  it('has no geographic or enabled-language constants in src or e2e', () => {
    const violations = ['src', 'e2e']
      .flatMap((dir) => files(join(root, dir)))
      .flatMap((path) => {
        const name = relative(root, path);
        if (name === 'src/api/schema.d.ts' || FIXTURES.has(name)) return [];
        return hardcodes(readFileSync(path, 'utf8')).map((kind) => `${name}: ${kind}`);
      });
    expect(violations).toEqual([]);
  });
});
