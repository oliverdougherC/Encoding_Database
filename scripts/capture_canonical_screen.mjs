#!/usr/bin/env node
// CC0-1.0. Original deterministic browser workload; see canonical-screen/README.md.
import { createHash } from 'node:crypto';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { homedir, platform, arch } from 'node:os';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const assets=join(root,'scripts/canonical-screen');
const out=resolve(process.env.SCREEN_OUTPUT || join(root,'.build/canonical-screen'));
const ffmpeg=resolve(process.env.FFMPEG || join(root,'client/bin/mac/ffmpeg'));
const ffprobe=resolve(process.env.FFPROBE || join(root,'client/bin/mac/ffprobe'));
const encodeOnly=process.argv.includes('--encode-only');
const previous=encodeOnly?JSON.parse(await readFile(join(out,'metadata.json'),'utf8')):null;
const modulePath=process.env.PLAYWRIGHT_MODULE || join(homedir(),'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs');
const executable=process.env.CHROMIUM_EXECUTABLE || join(homedir(),'Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell');
const sha=async p=>createHash('sha256').update(await readFile(p)).digest('hex');
const pwVersion=JSON.parse(await readFile(join(dirname(modulePath),'package.json'),'utf8')).version;
if(pwVersion!=='1.62.1')throw Error(`Expected Playwright 1.62.1, got ${pwVersion}`);
const {chromium}=await import(pathToFileURL(modulePath).href);
await mkdir(join(out,'frames'),{recursive:true});
const args=['--force-color-profile=srgb','--hide-scrollbars','--disable-lcd-text'];
const browser=await chromium.launch({headless:true,executablePath:executable,args});
const browserVersion=browser.version();
const hashes=[];
try {
 if(browserVersion!=='151.0.7922.34')throw Error(`Expected Chromium 151.0.7922.34, got ${browserVersion}`);
 if(!encodeOnly){
 const page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1,colorScheme:'light',locale:'en-US',timezoneId:'UTC',reducedMotion:'reduce'});
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.route(/^https?:/,route=>route.abort());
 await page.goto(pathToFileURL(join(assets,'workload.html')).href);
 await page.evaluate(()=>document.fonts.ready);
 if(!await page.evaluate(()=>document.fonts.check('17px Plex')))throw Error('Pinned font unavailable');
 for(let frame=0;frame<240;frame++){
   await page.evaluate(f=>window.renderFrame(f),frame);
   const file=join(out,'frames',`${String(frame).padStart(4,'0')}.png`);
   await page.screenshot({path:file,type:'png',animations:'disabled'});
   hashes.push({frame,sha256:await sha(file)});
 }
 if(errors.length)throw Error(errors.join('\n'));
 } else {
  for(const old of previous.frameHashes){
   const actual=await sha(join(out,'frames',`${String(old.frame).padStart(4,'0')}.png`));
   if(actual!==old.sha256)throw Error(`Frame ${old.frame} changed since capture`);
   hashes.push(old);
  }
  if(hashes.length!==240)throw Error('Expected 240 retained frames');
 }
} finally {await browser.close();}
const video=join(out,'screen-workload.mkv');
const encode=['-hide_banner','-y','-framerate','24','-i',join(out,'frames/%04d.png'),'-frames:v','240','-vf','format=gbrp,zscale=primariesin=bt709:transferin=iec61966-2-1:matrixin=gbr:rangein=full:primaries=bt709:transfer=bt709:matrix=bt709:range=limited,format=yuv420p','-c:v','ffv1','-level','3','-g','1','-slicecrc','1','-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-an',video];
const run=(cmd,args)=>execFileSync(cmd,args,{encoding:'utf8',maxBuffer:20*1024*1024});
execFileSync(ffmpeg,encode,{stdio:['ignore','ignore','pipe']});
const decode=['-hide_banner','-v','error','-xerror','-i',video,'-f','null','-'];
const decoded=execFileSync(ffmpeg,decode,{encoding:'utf8',stdio:['ignore','pipe','pipe']});
await writeFile(join(out,'full-decode.log'),`Full decode exit 0. No FFmpeg errors.\n${decoded}`);
const probe=JSON.parse(run(ffprobe,['-v','error','-count_frames','-show_streams','-show_format','-of','json',video]));
const s=probe.streams[0];
if(s.nb_read_frames!=='240'||s.width!==1920||s.height!==1080||s.pix_fmt!=='yuv420p'||s.r_frame_rate!=='24/1'||s.color_range!=='tv'||s.color_space!=='bt709'||s.color_transfer!=='bt709'||s.color_primaries!=='bt709'||Number(probe.format.duration)!==10)throw Error('Unexpected output properties');
await writeFile(join(out,'ffprobe.json'),JSON.stringify(probe,null,2)+'\n');
execFileSync(ffmpeg,['-hide_banner','-y','-i',video,'-vf',"select='eq(n,0)+eq(n,72)+eq(n,144)+eq(n,216)',scale=960:540,tile=2x2",'-frames:v','1',join(out,'contact-sheet.png')],{stdio:['ignore','ignore','pipe']});
const inputFiles=['workload.html','README.md','fonts/IBMPlexMono-Regular.ttf','fonts/OFL.txt'];
const inputs=await Promise.all(inputFiles.map(async file=>({file,sha256:await sha(join(assets,file))})));
const metadata={schema:'encodingdb-authored-screen-v1',createdAt:new Date().toISOString(),source:'Original offline browser application screen; fictional authored dataset',license:'CC0-1.0 authored content; SIL-OFL-1.1 IBM Plex Mono',fontSource:'https://raw.githubusercontent.com/google/fonts/142c8963e7606b510c93a644c82a4c4cdeae6ef9/ofl/ibmplexmono/IBMPlexMono-Regular.ttf',playwright:{version:pwVersion,modulePath,source:'https://github.com/microsoft/playwright/tree/v1.62.1'},browser:{version:browserVersion,executable,sha256:await sha(executable),revision:'1234',source:'https://cdn.playwright.dev/builds/cft/151.0.7922.34/mac-arm64/chrome-headless-shell-mac-arm64.zip',args},platform:{os:platform(),arch:arch(),node:process.version},viewport:{width:1920,height:1080,deviceScaleFactor:1},timeline:{fps:24,frames:240,durationSeconds:10,sourceScrollSeconds:[2,5],tableScrollSeconds:[5,8],rowSelectionSecond:8,clock:'frame index / 24'},inputs,captureCreatedAt:previous?.captureCreatedAt || previous?.createdAt || new Date().toISOString(),captureScriptSha256:previous?.captureScriptSha256 || await sha(fileURLToPath(import.meta.url)),preparationScriptSha256:await sha(fileURLToPath(import.meta.url)),tools:{ffmpeg:{path:ffmpeg,sha256:await sha(ffmpeg)},ffprobe:{path:ffprobe,sha256:await sha(ffprobe),version:run(ffprobe,['-version']).split('\n')[0]}},ffmpegVersion:run(ffmpeg,['-version']).split('\n')[0],encodeCommand:[ffmpeg,...encode],decodeCommand:[ffmpeg,...decode],validation:{fullDecodeExitCode:0,frameCount:240,visualReview:'pending integration-owner inspection'},output:{file:'screen-workload.mkv',sha256:await sha(video)},frameHashes:hashes};
await writeFile(join(out,'metadata.json'),JSON.stringify(metadata,null,2)+'\n');
console.log(JSON.stringify({output:video,sha256:metadata.output.sha256,browserVersion,frames:240,fullDecode:'passed'}));
