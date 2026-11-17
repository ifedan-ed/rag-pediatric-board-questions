// Revision runs for JMIR AI ms#113094.
//
// Runs inside the study app image so it uses the app's own prompt builder
// (questionPrompt), answer reader (extractSelectedOption) and tutor client
// (provider pins, retries, passage assembly). Nothing here re-implements those;
// it only wraps fetch to (a) record what the reader returned and what was sent
// to the model, (b) replay a stored retrieval, and (c) for the no-prefer arm,
// drop the two "prefer the context" sentences from the system message.
//
// Modes:
//   retrieve                     one live retrieval per question, stored in full
//   generate <arm> <rep>         arm = direct | rag_replay | rag_noprefer ; rep = run label
//                                rag_replay = the original retrieval prompt on the stored passages
//
// Output goes to /out (mounted). Every record is appended as one JSON line and
// the run resumes from whatever is already written, so it can be restarted.
'use strict';

const fs = require('fs');
const path = require('path');
const { createTutorClient, MODEL_ROUTES } = require('/app/src/services/tutorClient');
const { questionPrompt, extractSelectedOption, hashJson } = require('/app/src/utils/study');

const OUT = '/out';
const QUESTIONS = JSON.parse(fs.readFileSync('/data/questions.json', 'utf8')).slice(0, Number(process.env.LIMIT || 1e9));
const AUGUST = JSON.parse(fs.readFileSync('/data/august_generations.json', 'utf8'));
// The ten study models, taken from the August data (the image also routes gemini-3.1-pro, which was dropped).
const MODELS = Array.from(new Set(AUGUST.map(function(g) { return g.model; }))).sort();
if (MODELS.length !== 10 || MODELS.some(function(m) { return !MODEL_ROUTES[m]; })) throw new Error('study model list mismatch');
const PER_MODEL_CONCURRENCY = Number(process.env.PER_MODEL_CONCURRENCY || 3);

// The two sentences that make up the "prefer retrieved context" instruction in
// the original retrieval arm. The untrusted-data sentence and the format rule
// stay, so the only change is the preference instruction.
const PREFER_SENTENCES = ' Use the retrieved context for factual claims and prefer it over your own knowledge.'
  + ' Base the educational summary on the retrieved context as well.';

const augustHash = new Map();
for (const g of AUGUST) augustHash.set(g.qid, g.prompt_hash);

function promptFor(q) {
  // The pilot cohort had include_references = false.
  const prompt = questionPrompt({ stem: q.stem, options: q.options }, { includeReferences: false });
  if (hashJson(prompt) !== augustHash.get(q.qid)) {
    throw new Error('prompt for question ' + q.qid + ' does not match the August prompt hash');
  }
  return prompt;
}

function readDone(file, keyOf) {
  const done = new Set();
  if (!fs.existsSync(file)) return done;
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim()) continue;
    try { done.add(keyOf(JSON.parse(line))); } catch (_) { /* a torn last line is re-run */ }
  }
  return done;
}

function append(file, record) { fs.appendFileSync(file, JSON.stringify(record) + '\n'); }

function fakeResponse(body, headers) {
  return new Response(typeof body === 'string' ? body : JSON.stringify(body), {
    status: 200, headers: Object.assign({ 'content-type': 'application/json' }, headers || {})
  });
}

// Wraps fetch for one call. `opts.replay` is a stored reader response to serve
// instead of calling the reader; `opts.stopBeforeModel` answers the model call
// locally (retrieval only); `opts.noPrefer` edits the system message.
function wrappedFetch(capture, opts) {
  return async function(url, init) {
    const href = String(url);
    const body = init && typeof init.body === 'string' ? init.body : '';
    const isReader = href.startsWith(process.env.RAG_READER_URL.replace(/\/$/, ''));
    if (isReader && opts.replay) {
      if ((init.method || 'GET') === 'DELETE') return fakeResponse({});
      const msg = body ? JSON.parse(body) : {};
      if (msg.method === 'initialize') return fakeResponse({ jsonrpc: '2.0', id: 1, result: {} }, { 'mcp-session-id': 'replay' });
      if (msg.method === 'tools/call') return new Response(opts.replay, { status: 200, headers: { 'content-type': 'text/event-stream' } });
      return fakeResponse({});
    }
    if (href.endsWith('/chat/completions')) {
      const request = JSON.parse(body);
      if (opts.noPrefer) {
        const system = request.messages[0];
        if (system.role !== 'system' || !system.content.includes(PREFER_SENTENCES)) throw new Error('system prompt changed; refusing to edit it');
        system.content = system.content.replace(PREFER_SENTENCES, '');
        init = Object.assign({}, init, { body: JSON.stringify(request) });
      }
      if (opts.replay && !opts.noPrefer && !request.messages[0].content.includes(PREFER_SENTENCES)) {
        throw new Error('original retrieval prompt not found; refusing to run rag_replay');
      }
      capture.messages = request.messages;
      if (opts.stopBeforeModel) return fakeResponse({ choices: [{ message: { content: 'x' } }] });
    }
    const response = await fetch(url, init);
    if (isReader && body.includes('"tools/call"')) {
      const text = await response.clone().text();
      capture.readerText = text;
    }
    return response;
  };
}

async function pool(items, limit, worker) {
  let next = 0;
  async function lane() { while (next < items.length) { const item = items[next++]; await worker(item); } }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, lane));
}

// The reader quietly falls back to unreranked search when the reranker fails
// (seen 2026-11-16: Cohere returned 402), which would change the passages. So
// retrieval refuses to start unless a rerank call through the gateway succeeds.
async function rerankPreflight() {
  const base = new URL(process.env.STUDY_LITELLM_URL);
  base.pathname = '/rerank';
  const response = await fetch(base, { method: 'POST',
    headers: { Authorization: 'Bearer ' + process.env.LITELLM_MASTER_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: 'cohere-rerank-v4.0-pro', query: 'fever in infants', documents: ['fever in infants', 'coding manual'], top_n: 1 }) });
  if (!response.ok) throw new Error('reranker unavailable (' + response.status + '): ' + (await response.text()).slice(0, 200));
}

async function retrieveAll() {
  await rerankPreflight();
  const file = path.join(OUT, 'retrieval.jsonl');
  const done = readDone(file, function(r) { return r.qid; });
  let n = 0;
  await pool(QUESTIONS.filter(function(q) { return !done.has(q.qid); }), 4, async function(q) {
    const capture = {};
    const tutor = createTutorClient({ fetchImpl: wrappedFetch(capture, { stopBeforeModel: true }) });
    const started = Date.now();
    const result = await tutor.rag({ content: promptFor(q), model: 'phi-4' });
    const user = capture.messages[1].content;
    const ref = user.indexOf('<reference_material>');
    append(file, {
      qid: q.qid, retrieved_at: new Date().toISOString(), latency_ms: Date.now() - started,
      ids: result.metadata.retrievalIds, count: result.metadata.retrievalCount,
      reference_block: ref >= 0 ? user.slice(ref) : '',
      reader_text: capture.readerText
    });
    n += 1;
    if (n % 25 === 0) console.log('retrieved', n);
  });
}

async function generateAll(arm, rep) {
  if (!['direct', 'rag_replay', 'rag_noprefer'].includes(arm)) throw new Error('unknown arm ' + arm);
  const file = path.join(OUT, 'gen_' + arm + '_' + rep + '.jsonl');
  const done = readDone(file, function(r) { return r.model + '|' + r.qid; });
  let replay = null;
  if (arm !== 'direct') {
    // Both retrieval arms replay the same stored passages, so they differ only in the instruction.
    replay = new Map();
    for (const line of fs.readFileSync(path.join(OUT, 'retrieval.jsonl'), 'utf8').split('\n')) {
      if (line.trim()) { const r = JSON.parse(line); replay.set(r.qid, r.reader_text); }
    }
    if (QUESTIONS.some(function(q) { return !replay.has(q.qid); })) throw new Error('retrieval incomplete: ' + replay.size);
  }
  let n = 0;
  let failures = 0;
  await Promise.all(MODELS.map(function(model) {
    const todo = QUESTIONS.filter(function(q) { return !done.has(model + '|' + q.qid); });
    return pool(todo, PER_MODEL_CONCURRENCY, async function(q) {
      const capture = {};
      const tutor = createTutorClient({ fetchImpl: wrappedFetch(capture, { replay: replay && replay.get(q.qid), noPrefer: arm === 'rag_noprefer' }) });
      const input = { content: promptFor(q), model: model };
      let result;
      try {
        result = arm === 'direct' ? await tutor.direct(input) : await tutor.rag(input);
      } catch (error) {
        failures += 1;
        console.error('FAILED', model, q.qid, error.code, error.detail || '');
        return; // left out of the file, so a rerun picks it up
      }
      const m = result.metadata;
      append(file, {
        arm: arm, rep: rep, model: model, qid: q.qid, completed_at: new Date().toISOString(),
        answer_text: result.answer,
        selected: extractSelectedOption(result.answer, q.options.length),
        route_provider: m.routeProvider, provider_reported: m.providerReported,
        tokens: m.usage, cost: Number.isFinite(m.usage.cost) ? m.usage.cost : null,
        latency_ms: m.latencyMs, retrieval_count: m.retrievalCount, retrieval_ids: m.retrievalIds,
        system_prompt_hash: hashJson(capture.messages[0].content)
      });
      n += 1;
      if (n % 100 === 0) console.log(arm, rep, 'done', n);
    });
  }));
  console.log(arm, rep, 'finished; new', n, 'failed', failures);
}

(async function main() {
  const [mode, arm, rep] = process.argv.slice(2);
  if (mode === 'retrieve') await retrieveAll();
  else if (mode === 'generate') await generateAll(arm, rep || 'r1');
  else throw new Error('usage: retrieve | generate <direct|rag_replay|rag_noprefer> <rep>');
})().catch(function(error) { console.error(error); process.exit(1); });
