// Whether a component sits on a raised surface (a sheet). Pressed states step to a different fill
// there (phone-ux §3.3 `fillRaisedPressed`): in dark the raised surface already IS `fill`, so a
// row or a quiet button pressing to `fill` inside a sheet would show nothing.

import { createContext, useContext } from 'react';

import type { Theme } from '../theme/index.ts';

export const RaisedSurface = createContext(false);

export function useRaised(): boolean {
  return useContext(RaisedSurface);
}

/** The pressed fill for a row or a quiet control, on the page or inside a sheet. */
export function pressedFill(t: Theme, raised: boolean): string {
  return raised ? t.color.fillRaisedPressed : t.color.fill;
}
