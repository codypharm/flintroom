/**
 * One question a number invites.
 *
 * Shared by every tool, because the shape is the product's rather than any one
 * page's: a line that asks rather than concludes, a reason it gets asked for
 * the reader who has not been in the room yet, and a flag for whether it came
 * out of the figures somebody typed or off the standard list.
 *
 * The grounded ones are always listed first. A generic question at the top
 * reads as a listicle; one drawn from your own numbers reads as having been
 * listened to, which is the impression these pages exist to leave.
 */
export interface Question {
  id: string;
  /** The question itself, in the voice it would be asked in. */
  text: string;
  /** Why it gets asked, for the reader who has not been in the room yet. */
  why: string;
  /** True when this came out of their own numbers rather than the standard list. */
  grounded: boolean;
}
