// Leaderboard for 북항이의 대모험.
// Each score is its own blob key, so concurrent submissions never overwrite each other.
// Key layout:  all/<inverted score>-<time>-<rand>-<name>   and   day/<YYYY-MM-DD>/<same>
// Inverted, zero-padded scores make plain key order = highest score first.
import { getStore } from "@netlify/blobs";

const MAX_SCORE = 5_000_000;
const PAD = 10;
const store = () => getStore({ name: "bukhang-scores", consistency: "strong" });
const kstDay = (d = new Date()) => new Date(d.getTime() + 9 * 3600e3).toISOString().slice(0, 10);
const json = (body, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
});

function cleanName(raw) {
  const s = String(raw ?? "").replace(/[\u0000-\u001f\/\\%<>]/g, "").trim().slice(0, 12);
  return s || "익명 상어";
}
function parse(key) {
  const leaf = key.slice(key.lastIndexOf("/") + 1);
  const [inv, , , ...rest] = leaf.split("-");
  const score = Number("9".repeat(PAD)) - Number(inv);
  let name = rest.join("-");
  try { name = decodeURIComponent(name); } catch { /* keep raw */ }
  const [n, tier] = name.split("|");
  return { name: n, tier: tier || "", score };
}
async function top(prefix, limit) {
  const { blobs } = await store().list({ prefix });
  return blobs.map(b => b.key).sort().slice(0, limit).map(parse);
}

export default async (req) => {
  if (req.method === "GET") {
    const [all, today] = await Promise.all([top("all/", 50), top(`day/${kstDay()}/`, 20)]);
    return json({ all, today, day: kstDay() });
  }
  if (req.method === "POST") {
    let body;
    try { body = await req.json(); } catch { return json({ error: "잘못된 요청이에요" }, 400); }
    const score = Math.floor(Number(body?.score));
    if (!Number.isFinite(score) || score <= 0 || score > MAX_SCORE) return json({ error: "점수가 올바르지 않아요" }, 400);
    const name = cleanName(body?.name);
    const tier = String(body?.tier ?? "").slice(0, 12).replace(/[|\/%]/g, "");
    const inv = String(Number("9".repeat(PAD)) - score).padStart(PAD, "0");
    const leaf = `${inv}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}-${encodeURIComponent(name + "|" + tier)}`;
    const s = store();
    await Promise.all([s.set(`all/${leaf}`, "1"), s.set(`day/${kstDay()}/${leaf}`, "1")]);
    const rankAll = (await store().list({ prefix: "all/" })).blobs.map(b => b.key).sort().indexOf(`all/${leaf}`) + 1;
    return json({ ok: true, rank: rankAll });
  }
  return json({ error: "지원하지 않는 요청이에요" }, 405);
};

export const config = { path: "/api/scores" };
