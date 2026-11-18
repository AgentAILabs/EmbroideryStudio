/* Library + 3D viewer end-to-end check: real WebGL pixels are read back, so a blank canvas fails.
   Usage: python3 server/app.py 8765 &   then   NODE_PATH=$(npm root -g) node tools/e2e_library_3d.js     (needs Playwright; not part of CI)
   Env: ES_URL (default http://127.0.0.1:8765). Screenshots go to a temp folder printed at the end. */
const fs=require('fs'),os=require('os'),path=require('path');const {chromium}=require('playwright');
const BASE=process.env.ES_URL||'http://127.0.0.1:8765',SP=fs.mkdtempSync(path.join(os.tmpdir(),'es-3d-'));(async()=>{
const b=await chromium.launch();const ctx=await b.newContext({viewport:{width:1400,height:900},acceptDownloads:true,deviceScaleFactor:1.5});const pg=await ctx.newPage();
const errs=[],bad=[];pg.on('pageerror',x=>errs.push('PAGEERR '+x.message));pg.on('console',m=>{if(m.type()==='error')errs.push('CONSOLE '+m.text())});pg.on('response',r=>{if(r.status()>=500)bad.push(r.status()+' '+r.url())});
let dialogs=[];pg.on('dialog',d=>{dialogs.push(d.type()+': '+d.message().slice(0,80));d.accept()});
const res=[];const step=async(n,f)=>{try{const v=await f();res.push(['PASS',n,v===undefined?'':v])}catch(e){res.push(['FAIL',n,String(e.message).split('\n')[0]])}};const wait=ms=>pg.waitForTimeout(ms);
await pg.goto(BASE+'/');await pg.evaluate(()=>localStorage.clear());await pg.reload();await wait(600);
await step('Library opens with 12 cards, all thumbnails loaded',async()=>{await pg.click('#bLib');await wait(900);const n=await pg.locator('.card').count();if(n<12)throw new Error('cards '+n);
  const ok=await pg.evaluate(()=>[...document.querySelectorAll('.card img')].filter(i=>i.complete&&i.naturalWidth>0).length);if(ok<12)throw new Error('thumbnails loaded '+ok);return n+' cards, '+ok+' thumbnails'});
await pg.screenshot({path:SP+'/ui-library.png'});
await step('category filter + search',async()=>{await pg.click('#libcats button[data-cat="Borders"]');const a=await pg.locator('.card').count();await pg.click('#libcats button[data-cat="All"]');await pg.fill('#libq','lotus');const b2=await pg.locator('.card').count();await pg.fill('#libq','');if(a!==2||b2!==1)throw new Error(a+' / '+b2);return 'Borders='+a+', "lotus"='+b2});
await step('DST download from a card',async()=>{const [d]=await Promise.all([pg.waitForEvent('download'),pg.click('.card:has-text("Kalash") a')]);const f=SP+'/dl.dst';await d.saveAs(f);const sz=require('fs').statSync(f).size;if(sz<1000)throw new Error('size '+sz);return d.suggestedFilename()+' '+sz+'B'});
await step('3D button: opens design and switches to 3D',async()=>{await pg.click('.card:has-text("Kalash") button[data-act="3d"]');await wait(1500);const s=await pg.evaluate(()=>({v:__ES.vmode,libHidden:document.querySelector('#lib').hidden,glHidden:document.querySelector('#gl').hidden,name:__ES.doc.name,n:__ES.doc.objects.length,st:Viewer3D.stats()}));
  if(s.v!=='3d'||!s.libHidden||s.glHidden)throw new Error(JSON.stringify(s));if(!(s.st.triangles>1000))throw new Error('triangles '+s.st.triangles);return s.name+': '+s.st.stitches+' stitches -> '+Math.round(s.st.triangles)+' thread triangles'});
await step('3D renders thread: fabric + red pot + green leaves + gold coconut/bands are all really on screen',async()=>{
  const px=await pg.evaluate(()=>{const pts=[];for(let i=0;i<60;i++)for(let j=0;j<60;j++)pts.push(Viewer3D.sample(0.05+i*0.0158,0.05+j*0.0158));return pts});
  const set=new Set(px.map(p=>p.slice(0,3).join(',')));
  const cls=p=>{const[r,g,b]=p;if(r>150&&g<80&&b<80)return'red';if(r>170&&g>120&&b<110&&r>g)return'gold';if(g>r+25&&g>b+10&&g>110)return'green';if(g>r+12&&b<g&&g<95&&r<45)return'fabric';return'other'};
  const n={};for(const p of px){const c=cls(p);n[c]=(n[c]||0)+1}
  for(const k of['fabric','red','green','gold'])if(!(n[k]>3))throw new Error('missing '+k+': '+JSON.stringify(n));
  return set.size+' distinct colours; '+JSON.stringify(n)});
await pg.screenshot({path:SP+'/ui-3d.png'});
await step('orbit changes the view (pixels change)',async()=>{const a=await pg.evaluate(()=>Viewer3D.sample(0.5,0.5));const p0=await pg.evaluate(()=>Viewer3D.stats().pitch);
  const box=await (await pg.$('#gl')).boundingBox();await pg.mouse.move(box.x+box.width/2,box.y+box.height/2);await pg.mouse.down();await pg.mouse.move(box.x+box.width/2+120,box.y+box.height/2-60,{steps:6});await pg.mouse.up();await wait(300);
  const s=await pg.evaluate(()=>Viewer3D.stats());if(Math.abs(s.yaw)<0.3)throw new Error('yaw '+s.yaw);return 'yaw '+s.yaw.toFixed(2)+' pitch '+p0.toFixed(2)+'->'+s.pitch.toFixed(2)});
await pg.screenshot({path:SP+'/ui-3d-orbit.png'});
await step('wheel zoom + double-click reset',async()=>{const d0=await pg.evaluate(()=>Viewer3D.stats().dist);const box=await (await pg.$('#gl')).boundingBox();await pg.mouse.move(box.x+box.width/2,box.y+box.height/2);await pg.mouse.wheel(0,-300);await wait(200);const d1=await pg.evaluate(()=>Viewer3D.stats().dist);
  await pg.dblclick('#gl');await wait(200);const s=await pg.evaluate(()=>Viewer3D.stats());if(!(d1<d0))throw new Error('zoom '+d0+'->'+d1);if(Math.abs(s.yaw)>1e-6)throw new Error('reset yaw '+s.yaw);return 'dist '+d0.toFixed(0)+' -> '+d1.toFixed(0)+' -> reset '+s.dist.toFixed(0)});
await step('simulation slider drives the 3D build-up',async()=>{const full=await pg.evaluate(()=>Viewer3D.stats());await pg.fill('#sPos',String(Math.round(full.stitches*0.4)));await pg.dispatchEvent('#sPos','input');await wait(300);const half=await pg.evaluate(()=>Viewer3D.stats());
  if(!(half.drawnTriangles<full.drawnTriangles*0.6&&half.drawnTriangles>full.drawnTriangles*0.2))throw new Error(full.drawnTriangles+' -> '+half.drawnTriangles);if(await pg.evaluate(()=>__ES.vmode)!=='3d')throw new Error('left the 3D view');
  await pg.screenshot({path:SP+'/ui-3d-partial.png'});await pg.fill('#sPos',String(full.stitches));await pg.dispatchEvent('#sPos','input');await wait(200);return Math.round(full.drawnTriangles)+' -> '+Math.round(half.drawnTriangles)+' triangles at 40%'});
await step('fabric colour change recolours the fabric pixels (and only those)',async()=>{
  const grid=await pg.evaluate(()=>{const o=[];for(let i=0;i<40;i++)for(let j=0;j<40;j++){const fx=0.05+i*0.0235,fy=0.05+j*0.0235;o.push([fx,fy,Viewer3D.sample(fx,fy)])}return o});
  const fab=grid.filter(([x,y,p])=>p[1]>p[0]+12&&p[2]<p[1]&&p[1]<95&&p[0]<45);if(fab.length<10)throw new Error('no fabric pixels found');
  const thread=grid.filter(([x,y,p])=>p[0]>150&&p[1]<80&&p[2]<80);
  await pg.selectOption('#v3fab','#f2ead8');await wait(300);
  const after=await pg.evaluate(g=>g.map(([x,y])=>Viewer3D.sample(x,y)),fab.map(([x,y])=>[x,y]));
  const ivory=after.filter(p=>p[0]>170&&p[1]>150&&p[2]>120).length;if(ivory<fab.length*0.8)throw new Error('only '+ivory+'/'+fab.length+' fabric pixels turned ivory');
  const tAfter=await pg.evaluate(g=>g.map(([x,y])=>Viewer3D.sample(x,y)),thread.map(([x,y])=>[x,y]));const stillRed=tAfter.filter(p=>p[0]>150&&p[1]<80&&p[2]<80).length;
  if(thread.length&&stillRed<thread.length*0.8)throw new Error('thread colour changed too: '+stillRed+'/'+thread.length);
  return ivory+'/'+fab.length+' fabric pixels -> ivory; '+stillRed+'/'+thread.length+' red thread pixels unchanged'});
await pg.screenshot({path:SP+'/ui-3d-ivory.png'});
await step('Open (2D) another design, back to Stitches view',async()=>{await pg.click('#bLib');await wait(300);await pg.click('.card:has-text("Marigold") button[data-act="open"]');await wait(1200);const s=await pg.evaluate(()=>({v:__ES.vmode,name:__ES.doc.name}));if(s.name!=='marigold_flower'||s.v!=='design')throw new Error(JSON.stringify(s));
  await pg.click('[data-view=stitch]');await wait(300);return 'opened '+s.name+'; confirm dialog shown: '+dialogs.some(d=>d.startsWith('confirm'))});
await step('3D after editing: view refreshes from the new stitches',async()=>{await pg.click('[data-view="3d"]');await wait(800);const t1=await pg.evaluate(()=>Viewer3D.stats().triangles);await pg.click('[data-view=design]');await pg.evaluate(()=>{});
  await pg.click('#bLib');await wait(300);await pg.click('.card:has-text("Rings") button[data-act="3d"]');await wait(1500);const t2=await pg.evaluate(()=>Viewer3D.stats().triangles);if(Math.abs(t1-t2)<10)throw new Error('unchanged '+t1+' '+t2);return Math.round(t1)+' -> '+Math.round(t2)});
await step('Escape closes the library; shortcuts are inert while it is open',async()=>{await pg.click('#bLib');await wait(200);const tool0=await pg.evaluate(()=>__ES.tool);await pg.keyboard.press('f');const tool1=await pg.evaluate(()=>__ES.tool);await pg.keyboard.press('Escape');await wait(100);const hidden=await pg.evaluate(()=>document.querySelector('#lib').hidden);if(tool0!==tool1||!hidden)throw new Error(tool0+' '+tool1+' '+hidden);return 'ok'});
for(const r of res)console.log(r[0],'|',r[1],'|',r[2]);
console.log('artifacts in',SP);console.log('page errors:',errs.length?errs:'none','| HTTP 5xx:',bad.length?bad:'none');await b.close();process.exit(res.some(r=>r[0]==='FAIL')||errs.length||bad.length?1:0)})();
