/**
 * The waitlist, as one Vercel function against Resend.
 *
 * Deliberately independent of the app's backend: the FastAPI service is not
 * deployed anywhere public, and a marketing page must not wait for it to be.
 * Resend's Audience is the store of record — it holds the contacts, powers
 * the launch broadcast, and exports cleanly if the tool ever changes.
 *
 * Environment (set in the Vercel project, never committed):
 *   RESEND_API_KEY      the key from resend.com
 *   RESEND_AUDIENCE_ID  the Audience created for the waitlist
 *   RESEND_FROM         e.g. "Flintroom <hello@flintroom.app>" once the
 *                       domain is verified; falls back to Resend's test
 *                       sender so the flow works before DNS does.
 */

const RESEND = "https://api.resend.com";

module.exports = async (request, response) => {
  if (request.method !== "POST") {
    response.status(405).json({ error: "method_not_allowed" });
    return;
  }

  const { email, company } = request.body ?? {};

  // The honeypot. A field no person can see arrived filled, so a bot filled
  // it. Answer success: telling a bot it was caught only trains it.
  if (company) {
    response.status(200).json({ ok: true });
    return;
  }

  if (
    typeof email !== "string" ||
    email.length > 254 ||
    !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)
  ) {
    response.status(422).json({ error: "not_an_email" });
    return;
  }

  const key = process.env.RESEND_API_KEY;
  const audience = process.env.RESEND_AUDIENCE_ID;
  if (!key || !audience) {
    // Misconfiguration is ours, and the visitor should hear "try again",
    // not a stack of vendor words.
    console.error("waitlist_unconfigured");
    response.status(502).json({ error: "unavailable" });
    return;
  }

  const authed = { Authorization: `Bearer ${key}`, "Content-Type": "application/json" };

  // The contact first. Resend answers 201 for new and 409-shaped errors for
  // known; a repeat signup is a person double-checking, not a fault, so both
  // read as success.
  const added = await fetch(`${RESEND}/audiences/${audience}/contacts`, {
    method: "POST",
    headers: authed,
    body: JSON.stringify({ email, unsubscribed: false }),
  });
  if (!added.ok && added.status !== 409) {
    const already = added.status === 422; // Resend's shape for an existing contact
    if (!already) {
      console.error("waitlist_contact_refused", added.status);
      response.status(502).json({ error: "unavailable" });
      return;
    }
  }

  // The welcome. Best-effort: a failed email must not undo a stored signup,
  // so a refusal here is logged and the visitor still hears success.
  const sent = await fetch(`${RESEND}/emails`, {
    method: "POST",
    headers: authed,
    body: JSON.stringify({
      from: process.env.RESEND_FROM || "Flintroom <onboarding@resend.dev>",
      to: [email],
      subject: "You have a seat waiting",
      text: [
        "You are on the Flintroom waitlist.",
        "",
        "Flintroom is the room that grills you before the room that matters:",
        "a panel of AI interrogators that challenges your argument off your",
        "own deck, then a coach who rebuilds the answers that broke.",
        "",
        "You will get one email when we open. Android first, iOS after, and",
        "your first session is free.",
        "",
        "Until then, good luck in the rooms that matter.",
        "",
        "— Flintroom",
      ].join("\n"),
    }),
  });
  if (!sent.ok) {
    console.error("waitlist_welcome_refused", sent.status);
  }

  response.status(200).json({ ok: true });
};
