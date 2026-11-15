import { describe, expect, it } from 'vitest';
import { settle, splitBlocks } from './settle';

describe('settle', () => {
  it('shows an unclosed bold without its asterisks', () => {
    expect(settle('Многолетний тренд: **Мног')).toBe('Многолетний тренд: Мног');
    expect(settle('**Мног')).toBe('Мног');
  });

  it('leaves a bold that has closed', () => {
    expect(settle('**Многолетний тренд, ×0,73.**')).toBe('**Многолетний тренд, ×0,73.**');
    expect(settle('a **b** and **c')).toBe('a **b** and c');
  });

  it('holds back an unclosed emphasis, but not the star that opens a list item', () => {
    expect(settle('some *emph')).toBe('some emph');
    expect(settle('some *emph* done')).toBe('some *emph* done');
    expect(settle('* first\n* sec')).toBe('* first\n* sec');
    expect(settle('* first\n* *sec')).toBe('* first\n* sec');
  });

  it('holds back an unclosed code mark', () => {
    expect(settle('use `cod')).toBe('use cod');
    expect(settle('use `code` now')).toBe('use `code` now');
  });

  it('shows the words of a link that is not whole', () => {
    expect(settle('see [the page](https://exa')).toBe('see the page');
    expect(settle('see [the pa')).toBe('see the pa');
    expect(settle('see [the page](https://example.com)')).toBe(
      'see [the page](https://example.com)',
    );
  });

  it('touches only the last paragraph', () => {
    expect(settle('**open\n\nlater **x')).toBe('**open\n\nlater x');
  });
});

describe('splitBlocks', () => {
  it('parts paragraphs at the blank lines', () => {
    expect(splitBlocks('one\n\ntwo\n\n\nthree')).toEqual(['one', 'two', 'three']);
  });

  it('keeps a list with blank lines between its items in one block, so a numbered list goes on counting', () => {
    expect(splitBlocks('1. a\n\n2. b\n\n3. c')).toEqual(['1. a\n\n2. b\n\n3. c']);
    expect(splitBlocks('intro\n\n- a\n\n- b\n\nafter')).toEqual(['intro', '- a\n\n- b', 'after']);
  });
});
