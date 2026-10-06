// Build-time tools only. svg2ttf ships no types; this is the one call tools/icons_from_tile.ts makes.
declare module 'svg2ttf' {
  export default function svg2ttf(
    svg: string,
    options?: { ts?: number; version?: string; description?: string; url?: string },
  ): { buffer: Uint8Array };
}
