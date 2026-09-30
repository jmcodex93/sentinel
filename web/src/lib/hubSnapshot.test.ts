import { expect, it, vi } from 'vitest';
import { loadAssetDetails } from './hubSnapshot';
it('refreshes unchanged keys and replaces removed metadata and new siblings', async () => {
 const meta=vi.fn().mockResolvedValueOnce({same:{width:8000}}).mockResolvedValueOnce({same:{width:2000}}).mockResolvedValueOnce({});
 const variants=vi.fn().mockResolvedValueOnce({}).mockResolvedValueOnce({same:[{basename:'same_2k.png',px:2048}]}).mockResolvedValueOnce({});
 const read=()=>loadAssetDetails(['same'],meta,variants,async()=>null,()=>false);
 expect((await read())?.metas).toEqual({same:{width:8000}});
 expect(await read()).toMatchObject({metas:{same:{width:2000}},variants:{same:[{basename:'same_2k.png',px:2048}]}});
 expect(await read()).toMatchObject({metas:{},variants:{}});
});
it('bounds requests to 64 keys and abandons obsolete sweeps',async()=>{
 let cancelled=false;
 const meta=vi.fn(async(_keys: string[])=>{cancelled=true;return {};}); const variants=vi.fn(async()=>({})); const totals=vi.fn();
 expect(await loadAssetDetails(Array.from({length:130},(_,i)=>String(i)),meta,variants,totals,()=>cancelled)).toBeNull();
 expect(meta.mock.calls).toHaveLength(1); expect(meta.mock.calls[0][0]).toHaveLength(64); expect(totals).not.toHaveBeenCalled();
});
