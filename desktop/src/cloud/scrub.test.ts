import * as fs from 'node:fs';
import * as path from 'node:path';
import { describe, expect, it } from 'vitest';
import { homePattern } from '../log';
import { maskLegacyText, scrubDeep, scrubText } from './scrub';

// The vectors `tests/test_scrub.py` runs against `scrub.py`: one file, so a
// rule changes in both scrubbers or in neither.
const VECTORS = path.resolve(__dirname, '..', '..', '..', 'tests', 'fixtures', 'scrub_vectors.json');

interface Vector {
  name: string;
  input: string;
  names: string[];
  expected: string;
}

const vectors = (JSON.parse(fs.readFileSync(VECTORS, 'utf8')) as { vectors: Vector[] }).vectors;

describe('scrubText', () => {
  it('reads the shared vector file', () => {
    expect(vectors.length).toBeGreaterThan(0);
  });

  // No home pattern: a vector cannot depend on the machine it runs on.
  it.each(vectors.map((v) => [v.name, v] as const))('%s', (_name, vector) => {
    expect(scrubText(vector.input, vector.names, null)).toBe(vector.expected);
  });

  it('writes the home directory as ~ before the profile-folder rule sees it', () => {
    const home = homePattern('/home/zorblax', false);
    expect(scrubText('read /home/zorblax/x.log, not /home/zorblaxer/y', [], home)).toBe(
      'read ~/x.log, not /home/zorblaxer/y',
    );
    const windows = homePattern('C:\\Users\\zorblax', true);
    expect(scrubText('open c:/users/ZORBLAX/AppData failed', [], windows)).toBe('open ~/AppData failed');
  });

  it('matches names whole by Unicode letters, as Python does', () => {
    expect(scrubText('Jöran met jöran, not Jöranö', ['Jöran'], null)).toBe('<name> met <name>, not Jöranö');
    expect(scrubText('Straße and STRASSE', ['Straße'], null)).toBe('<name> and <name>');
  });

  it('matches a name with a space through its own pattern, ignoring case', () => {
    expect(scrubText('zorb lax won; Zorb Laxer lost', ['Zorb Lax'], null)).toBe('<name> won; Zorb Laxer lost');
  });

  it('drops a name the Arena ID rule already covers', () => {
    expect(scrubText('ABCDEFGH12345678IJKLMNOP90', ['ABCDEFGH12345678IJKLMNOP90'], null)).toBe('<id>');
  });
});

describe('maskLegacyText', () => {
  it('masks on [mtgo] lines only, keeping Windows line ends', () => {
    const text =
      'WARNING [mtgo] unrecognised hand size in Zorblax keeps 7\r\n' +
      'WARNING [web] unrecognised hand size in Zorblax keeps 7\r\n' +
      'WARNING [mtgo] card event before any game started: "Zorblax casts"\r\n';
    expect(maskLegacyText(text)).toBe(
      'WARNING [mtgo] unrecognised hand size in <masked>\r\n' +
        'WARNING [web] unrecognised hand size in Zorblax keeps 7\r\n' +
        'WARNING [mtgo] card event before any game started: <masked>\r\n',
    );
  });

  it('masks both names in a mulligan mismatch', () => {
    const line =
      "WARNING [mtgo] mulligan count mismatch for Zorblax: 'mulligans to' implied 1, 'begins the game' implied 2 (Zorblax begins)";
    expect(maskLegacyText(line)).toBe(
      "WARNING [mtgo] mulligan count mismatch for <masked>: 'mulligans to' implied 1, 'begins the game' implied 2 (<masked>)",
    );
  });
});

describe('scrubDeep', () => {
  it('scrubs strings at any depth and leaves keys and other values', () => {
    const value = { 'a@example.invalid': ['mail a@example.invalid', 3, { deep: 'Quuxling' }], flag: true };
    expect(scrubDeep(value, ['Quuxling'], null)).toEqual({
      'a@example.invalid': ['mail <email>', 3, { deep: '<name>' }],
      flag: true,
    });
  });

  it('leaves a skipped key alone and survives a cycle', () => {
    const value: Record<string, unknown> = { kept: { text: 'a@example.invalid' }, text: 'a@example.invalid' };
    value.self = value;
    expect(scrubDeep(value, [], null, new Set(['kept']))).toEqual({
      kept: { text: 'a@example.invalid' },
      text: '<email>',
      self: '[Circular]',
    });
  });
});
