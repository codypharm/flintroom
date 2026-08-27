# Google Play — Data safety form answers

**Status: derived from the implementation, 2026-08-27. Fill the form from this
sheet, not from memory** — a wrong answer here is an app-rejection lever, and
Google compares the form against observed app behaviour.

Two definitions the form uses that are easy to get backwards:

- **"Shared"** means transferred to a third party acting for *its own*
  purposes. Transfers to **service providers processing on our behalf**
  (ElevenLabs, Google's Gemini API, Supabase, Railway, Cloudflare R2,
  RevenueCat, Resend) are **not "sharing"** under Play's definition, provided
  each processes only to provide the service to us. Answer **"No"** to sharing
  throughout, and keep that defensible by never signing a vendor agreement
  that lets one use the data for its own ends — the [ACTION] items in
  `docs/privacy-policy.md` (Gemini paid tier, ElevenLabs data-use opt-out) are
  what keep this answer true.
- **"Collected"** means transmitted off the device. Everything below is
  collected in that sense; nothing is processed only ephemerally except where
  marked.

## Section: Data collection and security

| Question | Answer | Why |
| --- | --- | --- |
| Does your app collect or share any of the required user data types? | **Collects: yes. Shares: no.** | See definitions above |
| Is all user data encrypted in transit? | **Yes** | HTTPS to the API, WSS for the room socket, HTTPS presigned URLs to R2 |
| Do you provide a way for users to request deletion? | **Yes** | In-app account deletion (Settings), seven-day window; per-recording and per-material deletion besides |

Play also asks for an **account deletion web link** for any app that offers
account creation. **[ACTION — gap]** We have in-app deletion only. Before the
form is submitted, stand up one public web page (a paragraph and a mailto is
acceptable to Google) describing how to request deletion, and put its URL in
the form. Track this as a launch blocker; it is the one answer we cannot give
today.

## Section: Data types

| Play data type | Collected? | Optional? | Purpose | Notes |
| --- | --- | --- | --- | --- |
| **Personal info → Email address** | Yes | No (arrives with sign-in when the provider supplies it) | Account management | `auth_identities.email`; used for the deletion confirmation |
| **Personal info → User IDs** | Yes | No | Account management | Our account UUID; also keys RevenueCat purchases |
| **Audio → Voice or sound recordings** | Yes | Partly | App functionality | The mic is required for a room to work at all; *retention* of the mixed recording is optional (Settings switch) and per-tier |
| **Messages / Other user-generated content** | Yes | Partly | App functionality | Transcripts (always), attached material's extracted claims, the audience note, authored panelists, coach conversations |
| **Files and docs** | Yes | Yes | App functionality | Attached decks; source file deleted after extraction |
| **Photos** | Yes | Yes | App functionality | Slide/whiteboard photos, same lifecycle as decks |
| **Financial info → Purchase history** | Yes | Yes | App functionality | What was bought and when, via RevenueCat webhooks; card details never reach us — Google Play processes payment |
| **App activity → App interactions** | Yes | No | Analytics | `app_open` only: name, account, server time; first-party database, no analytics vendor |
| **App info and performance** | No | — | — | No crash/diagnostics SDK is integrated |
| **Location, Contacts, Calendar, Health, Web history, Device IDs** | No | — | — | Not collected anywhere in the schema |

**RevenueCat SDK caveat.** The `react-native-purchases` SDK itself transmits a
device-scoped app user ID and purchase tokens. RevenueCat publishes its own
recommended data-safety disclosures for apps embedding the SDK — check that
page while filling the form and fold in anything it adds beyond the table
above, rather than assuming this sheet is exhaustive for their SDK's traffic.

## Answers to the questions reviewers actually ask a mic app

- *Why does the app record audio?* A live, interruptible interrogation — the
  product is the conversation. Audio streams for transcription; keeping the
  recording afterwards is a user-controlled setting with per-tier windows.
- *Is audio used for advertising or profiling?* No. No ad SDK, no profiling,
  no analytics vendor; the one analytics event carries no content.
- *Can users delete their data?* Per-recording, per-material, and full-account
  deletion are all in the shipped app, each traced to enforcing code in
  `docs/privacy-policy.md` → "Where each figure comes from".
- *Is content used to train AI models?* Intended answer: no — pending the two
  [ACTION] items in `docs/privacy-policy.md` (Gemini paid tier confirmed,
  ElevenLabs data-use opt-out flipped). Do not submit the form before both.

## Order of operations before store submission

1. Flip the ElevenLabs data-use opt-out; confirm the Gemini key is on a paid
   billing account. (Keeps "Shares: no" and the training answer true.)
2. Stand up the account-deletion web page; note its URL.
3. Read the regions off the Supabase, Railway and Cloudflare dashboards and
   finish the international-transfer sentence in `docs/privacy-policy.md`.
4. Answer the Play content rating questionnaire; reconcile the children's
   sentence in the policy with the rating it produces.
5. Lawyer pass over `docs/privacy-policy.md`; publish it at a public URL.
6. Fill the Data safety form from this sheet; paste the policy URL into the
   store listing.
