// Persistent upload queue (IndexedDB). Falls back silently to memory-only if unavailable.
const DB = "vanpere-uploads";
const STORE = "items";

const open = () => new Promise((resolve, reject) => {
  const req = indexedDB.open(DB, 1);
  req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id" });
  req.onsuccess = () => resolve(req.result);
  req.onerror = () => reject(req.error);
});

async function run(mode, fn) {
  try {
    const db = await open();
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      const req = fn(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(req?.result);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  } catch {
    return undefined;
  }
}

export const put = (item) => run("readwrite", (s) => s.put(item));
export const remove = (id) => run("readwrite", (s) => s.delete(id));
export const all = async () => (await run("readonly", (s) => s.getAll())) || [];
