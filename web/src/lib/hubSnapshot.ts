/** One bounded sweep per accepted inventory snapshot or explicit refresh.
 * Replacing these maps (never merging with the previous sweep) drops stale
 * metadata when a file vanishes and discovers siblings at unchanged paths.
 */
export async function loadAssetDetails<M, V, T>(
  keys: string[], readMeta: (keys: string[]) => Promise<Record<string, M>>,
  readVariants: (keys: string[]) => Promise<Record<string, V>>,
  readTotals: () => Promise<T>, cancelled: () => boolean,
): Promise<{metas: Record<string, M>; variants: Record<string, V>; totals: T} | null> {
  const metas: Record<string, M> = {}, variants: Record<string, V> = {};
  for (let i = 0; i < keys.length; i += 64) {
    if (cancelled()) return null;
    const chunk = keys.slice(i, i + 64);
    const [metaBatch, variantBatch] = await Promise.all([readMeta(chunk), readVariants(chunk)]);
    if (cancelled()) return null;
    Object.assign(metas, metaBatch);
    Object.assign(variants, variantBatch);
  }
  if (cancelled()) return null;
  const totals = await readTotals();
  return cancelled() ? null : {metas, variants, totals};
}
