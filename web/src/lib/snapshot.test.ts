import { describe, expect, it, vi, afterEach } from 'vitest';
import { SnapshotChannel, type SnapshotRead } from './snapshot';
import { fetchPanelOverviewSnapshot, fetchHubInventorySnapshot, fetchNotesState, submitNotes } from './api';
const good = (stamp: string, value: string): SnapshotRead<string> => ({ stamp, result: {kind:'ok',data:value} });
function deferred<T>() { let resolve!: (value:T)=>void; const promise = new Promise<T>(r=>{resolve=r;}); return {promise, resolve}; }
afterEach(()=>vi.unstubAllGlobals());
describe('snapshot coordinator used by Panel and Hub',()=>{
 it('recovers from a failed read or null stamp',async()=>{
  const c=new SnapshotChannel(); const commit=vi.fn();
  await c.load(async()=>({stamp:null,result:{kind:'error',message:'offline'}}),commit);
  expect(c.needsRefresh('B')).toBe(true);
  await c.load(async()=>good('B','new'),commit,'B');
  expect(c.needsRefresh('B')).toBe(false);
 });
 it('rejects late A after B and does not start duplicate polls for B',async()=>{
  const c=new SnapshotChannel(); const a=deferred<SnapshotRead<string>>(); const b=deferred<SnapshotRead<string>>(); const commit=vi.fn();
  const first=c.load(()=>a.promise,commit,'A');
  expect(c.needsRefresh('B')).toBe(true);
  const second=c.load(()=>b.promise,commit,'B');
  expect(c.needsRefresh('B')).toBe(false);
  b.resolve(good('B','B')); await second;
  a.resolve(good('A','A')); await first;
  expect(commit.mock.calls.map(args=>args[0].result.data)).toEqual(['B']);
  expect(c.needsRefresh('B')).toBe(false);
 });
 it('keeps stamps independent across subviews and invalidates pending reads after mutations',async()=>{
  const overview=new SnapshotChannel(), render=new SnapshotChannel();
  await overview.load(async()=>good('A','overview'),()=>{});
  await render.load(async()=>good('B','render'),()=>{});
  expect(overview.needsRefresh('B')).toBe(true);
  expect(render.needsRefresh('B')).toBe(false);
  const old=deferred<SnapshotRead<string>>(); const commit=vi.fn();
  const loading=render.load(()=>old.promise,commit,'B'); render.invalidate();
  old.resolve(good('B','old')); await loading; expect(commit).not.toHaveBeenCalled();
 });
});
describe('real HTTP wrappers',()=>{
 it('gets data and stamp in one request, never a trailing stamp request',async()=>{
  vi.stubGlobal('window',{location:{search:''}});
  const fetch=vi.fn().mockResolvedValue({ok:true,json:async()=>({data:{scene:'B'},stamp:'B'})}); vi.stubGlobal('fetch',fetch);
  const result=await fetchPanelOverviewSnapshot();
  expect(result).toEqual({result:{kind:'ok',data:{scene:'B'}},stamp:'B'});
  expect(fetch).toHaveBeenCalledTimes(1); expect(fetch.mock.calls[0][0]).toContain('with_stamp=1');
 });
 it('does not disguise an inventory transport failure as a valid snapshot',async()=>{
  vi.stubGlobal('window',{location:{search:''}}); vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('offline')));
  const result=await fetchHubInventorySnapshot(); expect(result.stamp).toBeNull(); expect(result.result.kind).toBe('error');
 });
 it('round-trips Notes context and revision through the real wrappers',async()=>{
  vi.stubGlobal('window',{location:{search:''}});
  const state={notes_text:'draft',todos:[],scene_base:'A',context:'opaque',revision:'rev'};
  const fetch=vi.fn().mockResolvedValueOnce({ok:true,json:async()=>state}).mockResolvedValueOnce({ok:true,json:async()=>({ok:false,error:'scene_changed'})}); vi.stubGlobal('fetch',fetch);
  const read=await fetchNotesState(); expect(read).toEqual({kind:'ok',data:state});
  const response=await submitNotes(state); expect(response).toEqual({ok:false,error:'scene_changed'});
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toMatchObject({context:'opaque',revision:'rev',notes_text:'draft'});
 });
});
it('selection acknowledgement cannot replace a newer or pending snapshot',async()=>{
 const channel=new SnapshotChannel();
 await channel.load(async()=>good('A','A'),()=>{});
 await channel.load(async()=>good('B','B'),()=>{});
 channel.acknowledge('A-selected','A');
 expect(channel.currentStamp()).toBe('B');
 const pending=deferred<SnapshotRead<string>>(); const loading=channel.load(()=>pending.promise,()=>{},'C');
 channel.acknowledge('B-selected','B');
 pending.resolve(good('C','C')); await loading;
 expect(channel.currentStamp()).toBe('C');
});
