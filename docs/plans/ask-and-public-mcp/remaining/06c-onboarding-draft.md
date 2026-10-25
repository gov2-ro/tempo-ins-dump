# AQ-06C draft: connecting INS+ to a chat app (not published)

**Status: DRAFT for owner review, 2026-10-25.** Nothing here is live. The endpoint below is
the planned one; the public MCP is off in every deployment. Items marked **[OWNER]** are
publication blockers that only the owner can fill or approve. Hosted-client tests (section 5)
are `not_run`: they need a reachable test endpoint and accounts the owner authorizes.

Client documentation checked on 2026-10-25:
[Claude custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp),
[ChatGPT custom MCP server](https://developers.openai.com/plugins/deploy/connect-chatgpt).
Recheck both before publishing; menus and plan rules change.

---

## 1. Help page text (Romanian first)

### Conectează INS+ la aplicația ta de chat

INS+ pune la dispoziție statisticile publice ale INS (TEMPO Online) ca **instrumente** pe care
un asistent AI le poate folosi: caută indicatori, citește definițiile, extrage valori, compară
perioade, face clasamente și rulează calcule revizuite (de ex. intensitatea turistică pe județe).

- **Cine face ce.** Aplicația ta de chat (Claude, ChatGPT) poartă conversația și folosește
  modelul ei. INS+ primește doar cererile instrumentelor și întoarce date, cu sursa și
  generația datelor. INS+ nu are nevoie de nicio cheie API de model și nu apelează niciun model.
- **Limitele contului tău de chat se aplică.** Nu toate planurile permit conectori proprii
  (vezi mai jos).
- **Adresa serverului:** `https://api-ins.gov2.ro/mcp` **[OWNER: confirmă domeniul final]**.
  Nu e nevoie de autentificare (acces anonim, doar citire).

**Ce poți întreba** (exemple verificate pe candidatul local, 2026-10-25):
- „Care este intensitatea turistică pe județe în 2025? Dă-mi și linkul de dovezi.”
- „Câștigul salarial mediu net pe județe, cel mai recent an.”
- „Ce înseamnă rata șomajului?” (primești întâi întrebarea: înregistrat sau BIM/ILO)

**Ce nu face INS+** (limitări):
- Nu adună categorii care se suprapun și nu inventează totaluri. Când o sumă nu e sigură
  statistic, primești un refuz explicat, nu o cifră.
- Unele cereri sunt prea mari pentru serverul public (prea multe rânduri de citit). Primești
  atunci un mesaj „restrânge selecția”. Acum, chiar și restrânse la un județ, sunt refuzate:
  rata șomajului înregistrat pe județe și clasamentul orașelor dintr-un județ.
  **[OWNER: actualizează după fixul din backlog]**
- Datele sunt cele publicate de INS la data generației indicate în fiecare răspuns. Linkurile
  de dovezi refuză să se deschidă dacă datele s-au actualizat între timp, ca să nu prezinte
  date noi drept răspunsul citat.
- Asistentul tău poate greși când formulează răspunsul. Verifică cifrele importante prin
  linkul de dovezi.

**Ce date ajung la INS+.** Cererile instrumentelor: cuvintele de căutare (care pot conține
întreaga întrebare), codurile setului de date, filtrele, anii. Nu primim restul conversației.
Jurnalele serverului păstrează, pentru fiecare cerere, ora, adresa IP, calea (`/mcp`) și
statusul, iar pentru fiecare instrument: numele, rezultatul (ok/refuz), durata și mărimea
răspunsului. Textul căutărilor nu este scris în jurnale. Răspunsurile identice pot fi ținute
în memorie până la 5 minute, pentru viteză. **[OWNER: perioada de păstrare a jurnalelor la
Fly.io, contact, politica de confidențialitate și termenii]**

### Connect INS+ to your chat app (English)

INS+ exposes Romanian public statistics from INS (TEMPO Online) as **tools** an AI assistant can
use: find indicators, read definitions, fetch values, compare periods, rank areas and run
reviewed calculations (e.g. tourism intensity by county).

- **Who does what.** Your chat app runs the conversation with its own model. INS+ receives only
  the tool requests and returns data, with its source and data generation. INS+ needs no model
  API key and never calls a model.
- **Your chat account's limits apply.** Not every plan allows custom connectors (see below).
- **Server URL:** `https://api-ins.gov2.ro/mcp` **[OWNER: confirm the final domain]**. No sign-in
  (anonymous, read-only).

Examples and limitations as above. **Data that reaches INS+:** tool requests, meaning search
words (which can contain your whole question), dataset codes, filters and years, but not the
rest of your conversation. Server logs keep the time, IP address, path and status of each
request, plus each tool's name, outcome, duration and response size. Search text is not
logged. Identical answers may be cached in memory for up to 5 minutes.
**[OWNER: log retention, contact, privacy policy, terms]**

---

## 2. Claude setup (verified against the support article, 2026-10-25)

- **Plans:** Free (one custom connector), Pro, Max, Team and Enterprise. On Team, only Owners or
  Primary Owners add connectors; on Enterprise, Owners, Primary Owners or roles allowed to
  manage connectors. Members then click **Connect**.
- **Pro / Max / Free:** *Customize → Connectors → + Add → Add custom connector*. Enter the name
  `INS+` and the URL above, **Continue**, choose **No sign in**, then **Add**.
- **Team / Enterprise owner:** *Organization settings → Connectors → Add → Custom → Web*, with
  the same fields.
- Claude connects from Anthropic's cloud, so the server must be public on the internet (a
  local or VPN address does not work). To change the URL, remove the connector and add it again.

## 3. ChatGPT setup (developer documentation, 2026-10-25; eligibility unverified)

- *chatgpt.com/plugins → + → Add custom MCP server*. Name and description, then **Connection:**
  the public URL above (it includes `/mcp`). Authentication: none. Accept the risk warning,
  choose **Create as a plugin**, then review the discovered tools.
- **Plans: unverified.** OpenAI's page says only that "account and workspace policies apply".
  Third-party guides disagree on whether Plus can do this; they agree that Free cannot.
  **[OWNER: check with your account in 06C; publish only what was observed]**
- Do not promise that every ChatGPT account can connect.

## 4. Publication checklist

| Item | Status |
|---|---|
| Final MCP domain and URL | draft: `https://api-ins.gov2.ro/mcp` (not live) |
| Public MCP enabled in production | not done. Needs the AQ-01B Linux run and owner approval |
| Contact, privacy policy, terms, log retention | **[OWNER]** missing (publication blocker) |
| Help page published on the site | not done. This text is a draft; a page follows owner review |
| Claude: tested with a real account | not_run (06C) |
| ChatGPT: tested with a real account, plan noted | not_run (06C) |
| ChatGPT plugin package / directory listing | not started. A listing is out of scope until the pilot is done |
| Known limitations shown (county unemployment, city rankings refused) | in the text above; update after the fix |

## 5. Hosted-client test plan (to run when authorized)

For each client and account, record the product surface, plan or workspace, date, transport,
latency and the outcome of each step. An account without custom connectors is an access
limitation, not a pass.

1. Add the connector without any key; the eight tools are listed.
2. A fact with its evidence link (e.g. resident population of Cluj, latest year).
3. The tourism-intensity recipe; open its evidence ZIP.
4. A city ranking in a county, or its honest resource refusal.
5. A definition clarification (generic national unemployment → registered vs ILO).
6. An unsafe aggregation refused (e.g. summing overlapping age groups).
7. A follow-up on the same selection; compare its values with the web page.
8. Disconnect and reconnect; nothing breaks for lack of a session or credential.
9. Cold start (first call after idle) and a deliberately slow request (timeout message).

Endpoint for the test: a candidate image on Fly with `TEMPO_MCP_ENABLED=true`, or a
time-limited tunnel to a local candidate. Either one is an owner decision; nothing is
exposed without it.

## 6. Example check on the local candidate (2026-10-25)

Run with the official SDK client against `a6f41a1` serving the 06B stage (generation
`9b3e065d`, default public limits). Each line shows the question, then the call that
`discover_indicators` suggested, then the result of that call.

| Question | Suggested call | Result |
|---|---|---|
| intensitatea turistică pe județe 2025 | `run_recipe tourism_intensity 2025` | ok, 42 areas |
| câștigul salarial mediu net pe județe | `run_recipe net_earnings_county` | ok, 2024, 42 areas |
| rata șomajului | none (`needs_clarification`, `ambiguous_definition`) | asks registered vs ILO |
| rata șomajului în Cluj 2023 | `run_recipe registered_unemployment_county 2023 [Cluj]` | `unavailable/query_budget` (1,369,357 rows > 1,000,000) |
| cele mai mari orașe din județul Iași după populație | `rank_entities POP107D_grupe_localitate`, cities, Iasi | `unavailable/query_budget` (3,898,870 rows) |
| populația rezidentă a județului Cluj între 2015 și 2024 | `query_data POP105A_judete_grupe`, Cluj, **2024 only** | `partial/unverified_total`, 1 row |

The two refusals have one cause: the admission estimate is the whole file's footer
`num_rows`, so a county filter does not lower it (backlog P1). The population example asks
for a range but gets a one-year call with an unverified total, so it is not used as an
example (backlog).
