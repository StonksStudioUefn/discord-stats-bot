// Lo que no sale a la red de islas_jina.mjs: node --test herramientas/islas_jina.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { CODIGO, CREADOR, destinoValido, esperaDe, lotes, MAX_CUERPO, recortar, ritmo } from "./islas_jina.mjs";

test("códigos: solo los de isla y de creador, antes de montar una dirección", () => {
	assert.ok(CODIGO.test("1234-5678-9012"));
	for (const malo of ["1234-5678-901", "1234 5678 9012", "1234-5678-9012&x=1", "../1234-5678-9012"]) assert.ok(!CODIGO.test(malo), malo);
	assert.ok(CREADOR.test("dani280n2") && CREADOR.test("a_b-c"));
	for (const malo of ["Sonoq", "a/b", "a?b", "", "x".repeat(33), "a b"]) assert.ok(!CREADOR.test(malo), malo);
});

test("el pase solo va al servicio de verdad o a uno en local", () => {
	assert.ok(destinoValido("https://islas.stonksstudio.com"));
	assert.ok(destinoValido("http://localhost:8787"));
	assert.ok(destinoValido("http://127.0.0.1:1"));
	for (const malo of ["http://islas.stonksstudio.com", "https://islas.stonksstudio.com.malo.test", "https://otro.test", "no es url"]) assert.ok(!destinoValido(malo), malo);
});

test("recortar: por bytes y sin dejar un carácter partido", () => {
	assert.equal(recortar("hola", 10), "hola");
	assert.equal(recortar("ñññ", 5), "ññ");
	assert.ok(Buffer.byteLength(recortar("€".repeat(30_000), 64 * 1024)) <= 64 * 1024);
});

test("Retry-After: segundos, fecha o 60 s; con tope", () => {
	assert.equal(esperaDe("12"), 12_000);
	assert.equal(esperaDe(null), 60_000);
	assert.equal(esperaDe("luego"), 60_000);
	assert.equal(esperaDe("9999"), 120_000);
	assert.equal(esperaDe(new Date(1_000_030_000).toUTCString(), 1_000_000_000), 30_000);
});

test("ritmo: 15 por minuto son 4 s entre una y otra", async () => {
	let t = 0;
	const esperas = [];
	const turno = ritmo(15, () => t, async (ms) => {
		esperas.push(ms);
		t += ms;
	});
	for (let i = 0; i < 4; i++) await turno();
	assert.deepEqual(esperas, [0, 4_000, 4_000, 4_000]);
	t += 20_000;
	await turno();
	assert.equal(esperas.at(-1), 0, "tras un rato quieto, ya");
});

test("lotes: 10 como mucho y por debajo de los 600 KB", () => {
	const l = lotes(10);
	const llenos = [];
	for (let i = 0; i < 23; i++) {
		const r = l.meter(i % 2 ? "creadores" : "islas", { code: `c${i}`, title: "", content: "x" });
		if (r) llenos.push(r);
	}
	const resto = l.resto();
	assert.deepEqual([...llenos, resto].map((x) => x.islas.length + x.creadores.length), [10, 10, 3]);
	assert.equal(l.resto(), null);
	const g = lotes(10);
	const grandes = [];
	for (let i = 0; i < 10; i++) {
		const r = g.meter("islas", { code: `c${i}`, title: "", content: "x".repeat(64 * 1024) });
		if (r) grandes.push(r);
	}
	for (const x of [...grandes, g.resto()]) assert.ok(Buffer.byteLength(JSON.stringify(x)) <= MAX_CUERPO);
	assert.equal(grandes.length, 1, "9 de 64 KB caben; la décima, en otro");
	assert.equal(lotes(10, 1_000).meter("islas", { code: "x", title: "", content: "x".repeat(2_000) }), "grande");
});
