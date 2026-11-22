/* rAJIT virtual folder: serves dropped files under ./__vfs__/game/... so that a SWF loaded from
 * there can fetch its sibling files with ordinary relative URLs.
 * Files live in the Cache API (shared with the page, survives reloads and SW restarts). */
const CACHE = "rajit-vfs-v1";
const chan = new BroadcastChannel("rajit-vfs");

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

const SCOPE_PATH = new URL(self.registration.scope).pathname;   // e.g. /rAJIT/

self.addEventListener("fetch", (event) => {
    const { request } = event;
    const url = new URL(request.url);
    if (url.origin !== location.origin) return;
    if (url.pathname.includes("/__vfs__/")) {
        event.respondWith(serve(request, url));
    } else if (
        request.method === "GET" &&
        request.mode !== "navigate" &&
        url.pathname.startsWith(SCOPE_PATH) &&
        !url.pathname.slice(SCOPE_PATH.length).startsWith("ruffle-")
    ) {
        // Safety net: a relative URL that was resolved against the page instead of the SWF's folder
        // lands here. If the site has nothing at that address but a dropped file matches, serve it.
        event.respondWith(fallback(request, url));
    }
});

const SESSION = "game/";   // all dropped files live under __vfs__/game/

function relPath(url) {
    const p = decodeURIComponent(url.pathname);
    const rel = p.slice(p.indexOf("/__vfs__/") + "/__vfs__/".length);
    return rel.startsWith(SESSION) ? rel.slice(SESSION.length) : rel;
}

async function fallback(request, url) {
    const res = await fetch(request);
    if (res.status !== 404) return res;
    const cache = await caches.open(CACHE);
    const want = decodeURIComponent(url.pathname.slice(SCOPE_PATH.length)).toLowerCase();
    const base = (p) => p.slice(p.lastIndexOf("/") + 1);
    let byName = null;
    for (const key of await cache.keys()) {
        const have = relPath(new URL(key.url)).toLowerCase();
        if (have === want || have.endsWith("/" + want)) {
            chan.postMessage({ type: "request", method: request.method, path: want + "  (found next to the SWF)", status: 200 });
            return cache.match(key);
        }
        if (!byName && base(have) === base(want)) byName = key;
    }
    if (byName) {
        chan.postMessage({ type: "request", method: request.method, path: want + "  (matched by file name)", status: 200 });
        return cache.match(byName);
    }
    return res;
}

async function serve(request, url) {
    const cache = await caches.open(CACHE);
    const path = relPath(url);
    // Exact match first (query strings like ?nocache=123 are ignored)...
    let res = await cache.match(url.origin + url.pathname, { ignoreSearch: true });
    // ...then case-insensitive, because Flash content often doesn't care about case.
    if (!res) {
        const want = path.toLowerCase();
        for (const key of await cache.keys()) {
            if (relPath(new URL(key.url)).toLowerCase() === want) {
                res = await cache.match(key);
                break;
            }
        }
    }
    chan.postMessage({ type: "request", method: request.method, path, status: res ? 200 : 404 });
    if (!res) {
        return new Response("Not among the dropped files: " + path, {
            status: 404,
            headers: { "Content-Type": "text/plain" },
        });
    }
    return res;
}
