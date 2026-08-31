import { describe, expect, it } from 'vitest';

import { clampPercent, formatMonth, formatMonths, formatNumber, parseAmount, sanitizeTyping } from './amount';

/**
 * Reading and writing the numbers on a calculator page.
 *
 * Small enough to look obvious, and the source of most of the ways a
 * calculator embarrasses itself: pasting "$600,000" from a spreadsheet, an
 * empty field rendering as NaN, or claiming to know the day the money runs out.
 */

describe('reading what somebody typed', () => {
  it('accepts a figure pasted straight out of a spreadsheet', () => {
    expect(parseAmount('$600,000')).toBe(600_000);
  });

  it('accepts the separators people actually use', () => {
    expect(parseAmount('600 000')).toBe(600_000);
    expect(parseAmount('600,000')).toBe(600_000);
    expect(parseAmount('600000')).toBe(600_000);
  });

  it('keeps the decimal point', () => {
    expect(parseAmount('12.5')).toBe(12.5);
  });

  it('keeps a minus sign, so the maths can decide what to do with it', () => {
    // Cutting spend by 20% is a real thing to model. Silently dropping the sign
    // here would turn it into a 20% increase.
    expect(parseAmount('-20')).toBe(-20);
  });

  it('returns NaN for nothing, rather than a confident zero', () => {
    // `Number('')` is 0, and a blank cash field reported as "0 months" reads as
    // an answer when it is an absence.
    expect(parseAmount('')).toBeNaN();
    expect(parseAmount('   ')).toBeNaN();
    expect(parseAmount('abc')).toBeNaN();
  });
});

describe('writing it back out', () => {
  it('groups thousands, because the figure is meant to be read aloud', () => {
    expect(formatNumber(600_000)).toBe('600,000');
  });

  it('rounds money to whole units', () => {
    expect(formatNumber(12_345.67)).toBe('12,346');
  });

  it('names a month rather than a day', () => {
    // The model knows the month. Printing "11 November 2026" would claim a
    // precision that compounding assumptions do not support, and a founder
    // would quote the day back to somebody.
    expect(formatMonth(new Date('2026-11-01T00:00:00Z'))).toBe('November 2026');
  });

  it('keeps one decimal on the month count, and the singular on one', () => {
    expect(formatMonths(10)).toBe('10 months');
    expect(formatMonths(10 / 3)).toBe('3.3 months');
    expect(formatMonths(1)).toBe('1 month');
  });
});

describe('what the field lets you type', () => {
  it('drops letters and symbols as they arrive', () => {
    // `type="text"` is what makes a pasted "$600,000" survive, and it is also
    // what lets somebody type "abc". Sanitising on the way in is better than
    // an error message on the way out: there is no invalid state to explain.
    expect(sanitizeTyping('6a0b0c', { negative: false })).toBe('600');
    expect(sanitizeTyping('60#0!', { negative: false })).toBe('600');
  });

  it('keeps the separators a person pastes, and sorts them out on blur', () => {
    expect(sanitizeTyping('$600,000', { negative: false })).toBe('600,000');
    expect(sanitizeTyping('600 000', { negative: false })).toBe('600 000');
  });

  it('allows exactly one decimal point', () => {
    expect(sanitizeTyping('12.5', { negative: false })).toBe('12.5');
    expect(sanitizeTyping('12.5.7', { negative: false })).toBe('12.57');
  });

  it('lets a growth field go negative, and a cash field not', () => {
    // Modelling a cut is a real thing to do. Negative cash in the bank is not
    // a thing this page can say anything useful about.
    expect(sanitizeTyping('-20', { negative: true })).toBe('-20');
    expect(sanitizeTyping('-20', { negative: false })).toBe('20');
  });

  it('allows a minus only at the front', () => {
    expect(sanitizeTyping('2-0', { negative: true })).toBe('20');
  });

  it('leaves a half-typed number alone', () => {
    // "-" and "." are what a field looks like mid-keystroke. Rewriting them
    // under the caret is how a field fights the person using it.
    expect(sanitizeTyping('-', { negative: true })).toBe('-');
    expect(sanitizeTyping('.', { negative: false })).toBe('.');
    expect(sanitizeTyping('', { negative: false })).toBe('');
  });
});

describe('what survives leaving the field', () => {
  it('holds a growth rate to something a business could have', () => {
    // Below -100% spend would cross zero and start paying money in. Above
    // +100% a month is not a rate, it is a typo.
    expect(clampPercent(5)).toBe(5);
    expect(clampPercent(-250)).toBe(-100);
    expect(clampPercent(900)).toBe(100);
  });

  it('treats an empty growth field as flat', () => {
    expect(clampPercent(Number.NaN)).toBe(0);
  });
});
