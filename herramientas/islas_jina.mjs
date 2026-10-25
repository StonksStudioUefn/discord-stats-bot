// Lee por r.jina.ai, desde un runner de GitHub, las miniaturas de las islas y las fotos de los
// creadores que el servicio de islas de STONKS no consigue desde Cloudflare (Jina sin clave da
// 429 a su IP de salida, que comparten miles), y se las da. Lo lanza
// .github/workflows/islas-jina.yml. Node 20 o más nuevo, sin dependencias.
//
// Los logs de este repo son públicos: solo cuentas y tiempos. Nunca códigos, direcciones,
// títulos, lo que contesta Jina ni el pase.
//
// SECO=1: pide los pendientes y lee a Jina, pero no manda nada al servicio. Para probar en
// local: ISLAS_URL=http://localhost:8787 y JINA_URL=<un Jina de mentira>.
import { pathToFileURL } from "node:url";

const SERVICIO = process.env.ISLAS_URL || "https://islas.stonksstudio.com";
const JINA = process.env.JINA_URL || "https://r.jina.ai/";
const SECO = process.env.SECO === "1";
const AUDIENCIA = "islas.stonksstudio.com";
const AGENTE = "stonks-islas desde GitHub (discord-stats-bot)";

// Jina sin clave deja 20 por minuto por IP: con 15 queda margen para un reintento.
export const POR_MINUTO = 15;
const ESPERA_JINA = 30_000;
const ESPERA_429 = 60_000;
const MAX_ESPERA_429 = 120_000;
const ESPERA_SERVICIO = 30_000;
// Lo que admite el servicio: 10 por petición, 600 KB y 64 KB cada «content».
export const MAX_CONTENT = 64 * 1024;
const MAX_TITULO = 1_000;
export const MAX_CUERPO = 600 * 1024 - 4 * 1024;
const MAX_LOTE = 10;
// El flujo tiene 15 minutos: lo que no se ha leído en 11 se queda para mañana.
const PRESUPUESTO = 11 * 60_000;

export const CODIGO = /^\d{4}-\d{4}-\d{4}$/;
export const CREADOR = /^[a-z0-9_-]{1,32}$/;

/** El pase solo va al servicio de verdad, o a uno en local para probar. */
export function destinoValido(url) {
	try {
		const u = new URL(url);
		if (u.protocol === "https:") return u.host === "islas.stonksstudio.com";
		return u.protocol === "http:" && ["localhost", "127.0.0.1"].includes(u.hostname);
	} catch {
		return false;
	}
}

/** Como mucho `max` bytes en UTF-8, sin dejar un carácter partido al final. */
export function recortar(texto, max) {
	const b = Buffer.from(texto, "utf8");
	if (b.length <= max) return texto;
	return b.subarray(0, max).toString("utf8").replace(/�+$/, "");
}

/** Retry-After en ms (segundos o fecha); sin él, 60 s. Con tope: el flujo tiene 15 minutos. */
export function esperaDe(v, ahora = Date.now()) {
	let ms = ESPERA_429;
	if (v && /^\d+$/.test(v.trim())) ms = Number(v.trim()) * 1000;
	else if (v && !Number.isNaN(Date.parse(v))) ms = Math.max(0, Date.parse(v) - ahora);
	return Math.min(ms, MAX_ESPERA_429);
}

const dormir = (ms) => (ms > 0 ? new Promise((r) => setTimeout(r, ms)) : Promise.resolve());

/** Turnos: cada llamada espera a que hayan pasado 60/porMinuto s desde el turno anterior. */
export function ritmo(porMinuto, reloj = () => Date.now(), esperar = dormir) {
	const hueco = 60_000 / porMinuto;
	let siguiente = 0;
	return async () => {
		const ahora = reloj();
		const t = Math.max(ahora, siguiente);
		siguiente = t + hueco;
		await esperar(t - ahora);
	};
}

/** Lotes de `max` y menos de `maxBytes`: meter() da el lote lleno que haya que mandar. */
export function lotes(max = MAX_LOTE, maxBytes = MAX_CUERPO) {
	let actual = { islas: [], creadores: [] };
	const n = (l) => l.islas.length + l.creadores.length;
	const pesa = (l) => Buffer.byteLength(JSON.stringify(l));
	return {
		/** null si cabe; el lote de antes si no; "grande" si ni sola cabe (no se manda). */
		meter(tipo, leida) {
			const solo = { islas: [], creadores: [] };
			solo[tipo].push(leida);
			if (pesa(solo) > maxBytes) return "grande";
			const con = { ...actual, [tipo]: [...actual[tipo], leida] };
			if (n(con) <= max && pesa(con) <= maxBytes) {
				actual = con;
				return null;
			}
			const lleno = actual;
			actual = solo;
			return lleno;
		},
		/** Lo que quede, o null. */
		resto() {
			const l = actual;
			actual = { islas: [], creadores: [] };
			return n(l) ? l : null;
		},
	};
}

class Fallo extends Error {}

async function pase() {
	const url = process.env.ACTIONS_ID_TOKEN_REQUEST_URL;
	const token = process.env.ACTIONS_ID_TOKEN_REQUEST_TOKEN;
	if (!url || !token) {
		if (SECO) return null;
		throw new Fallo("Sin pase de GitHub: el flujo necesita «permissions: id-token: write».");
	}
	let r;
	try {
		r = await fetch(`${url}&audience=${encodeURIComponent(AUDIENCIA)}`, { headers: { Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(15_000) });
	} catch {
		throw new Fallo("GitHub no ha dado el pase: no contesta.");
	}
	const j = await r.json().catch(() => null);
	if (!r.ok || typeof j?.value !== "string") throw new Fallo(`GitHub no ha dado el pase (${r.status}).`);
	return j.value;
}

/** Un pase nuevo en cada petición: duran minutos y la vuelta entera puede pasar de diez. */
async function alServicio(ruta, cuerpo) {
	const token = await pase();
	let r;
	try {
		r = await fetch(`${SERVICIO}/publico/github/${ruta}`, {
			method: "POST",
			headers: { "content-type": "application/json", "user-agent": AGENTE, ...(token ? { authorization: `Bearer ${token}` } : {}) },
			body: JSON.stringify(cuerpo),
			signal: AbortSignal.timeout(ESPERA_SERVICIO),
		});
	} catch {
		return { status: 0, j: {} };
	}
	return { status: r.status, j: await r.json().catch(() => ({})) };
}

// El error lo escribe el servicio (textos fijos); lo de otro (el WAF, un proxy) no se imprime.
const porQue = (j) => (typeof j?.error === "string" ? `: ${j.error.slice(0, 200).replace(/\.$/, "")}` : "");
const servicioCaido = (status) => status === 0 || status === 401 || status === 403 || status >= 500;

async function leerJina(destino, turno, cuenta) {
	for (let intento = 0; intento < 2; intento++) {
		await turno();
		let r;
		try {
			r = await fetch(`${JINA}${destino}`, { headers: { Accept: "application/json", "User-Agent": AGENTE }, signal: AbortSignal.timeout(ESPERA_JINA) });
		} catch {
			cuenta.red++;
			return null;
		}
		if (r.status === 429) {
			await r.body?.cancel();
			cuenta.n429++;
			if (intento === 0) {
				await dormir(esperaDe(r.headers.get("retry-after")));
				continue;
			}
			return null;
		}
		if (!r.ok) {
			await r.body?.cancel();
			cuenta.otros++;
			return null;
		}
		const d = (await r.json().catch(() => null))?.data;
		if (!d || typeof d.content !== "string") {
			cuenta.otros++;
			return null;
		}
		return { title: typeof d.title === "string" ? d.title.slice(0, MAX_TITULO) : "", content: recortar(d.content, MAX_CONTENT) };
	}
	return null;
}

export async function principal() {
	const t0 = Date.now();
	if (!destinoValido(SERVICIO)) throw new Fallo("ISLAS_URL no es el servicio de islas ni uno en local: el pase no sale de aquí.");
	const p = await alServicio("pendientes", {});
	if (p.status !== 200 || !Array.isArray(p.j.islas) || !Array.isArray(p.j.creadores)) throw new Fallo(`El servicio no ha dado los pendientes (${p.status})${porQue(p.j)}.`);
	const islas = p.j.islas.filter((c) => typeof c === "string" && CODIGO.test(c));
	const creadores = p.j.creadores.filter((c) => typeof c === "string" && CREADOR.test(c));
	const max = Number.isInteger(p.j.max_lote) && p.j.max_lote > 0 ? Math.min(p.j.max_lote, MAX_LOTE) : MAX_LOTE;
	console.log(`Pendientes: ${islas.length} islas y ${creadores.length} creadores (lotes de ${max}${SECO ? ", en seco" : ""}).`);

	const turno = ritmo(POR_MINUTO);
	const cuenta = { leidas: 0, n429: 0, red: 0, otros: 0, sinTiempo: 0, grandes: 0 };
	const total = { lotes: 0, rechazados: 0, islas: { ok: 0, sin: 0, ignoradas: 0, nombres: 0 }, creadores: { ok: 0, sin: 0, ignoradas: 0 } };
	let caido = null;
	const mandar = async (lote) => {
		if (SECO || caido || !lote) return;
		const r = await alServicio("resultados", lote);
		if (r.status === 200) {
			total.lotes++;
			for (const tipo of ["islas", "creadores"]) for (const k of Object.keys(total[tipo])) total[tipo][k] += Number(r.j?.[tipo]?.[k]) || 0;
		} else if (servicioCaido(r.status)) caido = `El servicio no ha aceptado lo leído (${r.status})${porQue(r.j)}.`;
		else total.rechazados++;
	};
	const l = lotes(max);
	const trabajo = [
		...islas.map((code) => ["islas", code, `https://fortnite.gg/island?code=${code}`]),
		...creadores.map((code) => ["creadores", code, `https://fortnite.gg/creator/${code}`]),
	];
	for (const [tipo, code, destino] of trabajo) {
		if (caido) break;
		if (Date.now() - t0 > PRESUPUESTO) {
			cuenta.sinTiempo++;
			continue;
		}
		const leida = await leerJina(destino, turno, cuenta);
		if (!leida) continue;
		cuenta.leidas++;
		const lleno = l.meter(tipo, { code, ...leida });
		if (lleno === "grande") cuenta.grandes++;
		else await mandar(lleno);
	}
	await mandar(l.resto());

	const s = Math.round((Date.now() - t0) / 1000);
	console.log(`Jina: ${cuenta.leidas} leídas de ${trabajo.length}; 429: ${cuenta.n429}, sin red: ${cuenta.red}, otros fallos: ${cuenta.otros}, sin tiempo: ${cuenta.sinTiempo}, demasiado grandes: ${cuenta.grandes}.`);
	if (!SECO) {
		const { islas: i, creadores: c } = total;
		console.log(`Servicio: ${total.lotes} lotes guardados, ${total.rechazados} rechazados; islas ${i.ok} con miniatura, ${i.sin} sin, ${i.nombres} nombres, ${i.ignoradas} ignoradas; creadores ${c.ok} con foto, ${c.sin} sin, ${c.ignoradas} ignorados.`);
	}
	console.log(`En ${s} s.`);
	if (caido) throw new Fallo(caido);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
	principal().catch((e) => {
		// Un Fallo es un texto nuestro; de lo demás, solo el tipo: el mensaje podría llevar una dirección.
		console.error(e instanceof Fallo ? e.message : `Ha fallado el script (${e?.name ?? "error"}).`);
		process.exit(1);
	});
}
