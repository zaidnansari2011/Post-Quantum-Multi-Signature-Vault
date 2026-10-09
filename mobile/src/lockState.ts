// Whether app lock holds the app right now (phone-ux §6.1), readable outside React's tree.
//
// Every RN `<Modal>` (each sheet, the acknowledgement) and each native modal screen (New decision,
// New vault) draws in its own window or view controller, above the root view. A lock drawn in the
// root alone would sit UNDER an open sheet. So, the moment the app locks:
//   - every dismissible sheet closes itself, and the acknowledgement closes (`useCloseOnLock`);
//   - a modal form keeps its draft but draws the lock over itself (`LockGate`), with its content
//     hidden from screen readers;
//   - the root draws the lock screen in a full-screen `<Modal>`, mounted last.
// A sheet with a signature in flight is not dismissible; the lock draws over it, and the signature
// settles under the lock as it would have.
//
// No React import here: the store is plain, and src/ui reads it through `useAppLocked`.

type Listener = () => void;

let locked = false;
const listeners = new Set<Listener>();

export function setAppLocked(next: boolean): void {
  if (next === locked) return;
  locked = next;
  for (const listener of [...listeners]) listener();
}

export function isAppLocked(): boolean {
  return locked;
}

export function subscribeAppLock(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
