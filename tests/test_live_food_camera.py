"""Live camera lifecycle and capture concurrency use the actual browser module."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(0, "utf8");
class Target {
  constructor() {this.listeners=new Map();}
  addEventListener(type,fn) {
    if (!this.listeners.has(type)) this.listeners.set(type,new Set());
    this.listeners.get(type).add(fn);
  }
  removeEventListener(type,fn) {this.listeners.get(type)?.delete(fn);}
  fire(type) {for (const fn of Array.from(this.listeners.get(type)||[])) fn();}
}
const timers=new Map();
let timerId=0;
globalThis.setTimeout=(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id;};
globalThis.clearTimeout=id=>timers.delete(id);
globalThis.window=globalThis;
const windowEvents=new Target();
globalThis.addEventListener=windowEvents.addEventListener.bind(windowEvents);
globalThis.removeEventListener=windowEvents.removeEventListener.bind(windowEvents);
globalThis.isSecureContext=true;
const canvases=[];
const document=new Target();
document.hidden=false;
document.createElement=tag=>{
  assert.equal(tag,"canvas");
  const canvas={width:0,height:0,draws:[],getContext(){
    return {drawImage(...args){canvas.draws.push(args);}};
  }};
  canvases.push(canvas);
  return canvas;
};
globalThis.document=document;
const requests=[];
let acquisition=null;
class Track extends Target {
  constructor() {super();this.stopped=0;}
  stop() {this.stopped++;}
}
function makeStream() {
  const videoTrack=new Track(),otherTrack=new Track();
  return {videoTrack,otherTrack,getTracks(){return [videoTrack,otherTrack];},getVideoTracks(){return [videoTrack];}};
}
const streams=[];
Object.defineProperty(globalThis,"navigator",{configurable:true,value:{mediaDevices:{
  async getUserMedia(constraints) {
    requests.push(constraints);
    if(acquisition) return acquisition.promise;
    const stream=makeStream();streams.push(stream);return stream;
  }
}}});
function deferred() {let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};}
async function flush() {for(let i=0;i<30;i++)await Promise.resolve();}
async function runTimer() {
  assert.equal(timers.size,1,"recognition schedules only one pending frame");
  const [id,entry]=timers.entries().next().value;
  timers.delete(id);
  assert.equal(entry.ms,700,"recognition must be bounded between jobs");
  entry.fn();await flush();
}
function video(width=4000,height=3000) {
  return {srcObject:null,videoWidth:width,videoHeight:height,readyState:4,
    playsInline:false,muted:false,plays:0,pauses:0,
    async play(){this.plays++;},pause(){this.pauses++;}};
}
function setup(extra={}) {
  const result={video:video(),frames:[],captures:[],errors:[],statuses:[],valid:true};
  result.camera=LiveFoodCamera.create({
    video:result.video,
    onFrame:async canvas=>{result.frames.push(canvas);return null;},
    onCapture:async (canvas,detection)=>{result.captures.push({canvas,detection});},
    onError:error=>result.errors.push(error),onStatus:text=>result.statuses.push(text),
    isCurrent:()=>result.valid,...extra
  });
  return result;
}
vm.runInThisContext(source,{filename:"live_food_camera.js"});
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is needed for live camera behavior checks")
class LiveFoodCameraTests(unittest.TestCase):
    def run_camera(self, assertions):
        program = HARNESS + "\n(async()=>{\n" + assertions + r"""
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result = subprocess.run([shutil.which("node"), "-e", program],
                                input=(ROOT / "static/live_food_camera.js").read_text(encoding="utf-8"),
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rear_camera_preview_and_one_automatic_high_resolution_capture(self):
        self.run_camera(r"""
const detection={key:"barcode:0123456789012",code:"0123456789012"};
const frames=[],captures=[];
const item=setup({onFrame:async canvas=>{frames.push(canvas);return detection;},
  onCapture:async(canvas,result)=>captures.push({canvas,result})});
assert.equal(await item.camera.start(),true);
assert.equal(item.video.srcObject,streams[0]);
assert.equal(item.video.playsInline,true);
assert.equal(item.video.muted,true);
assert.deepEqual(requests,[{audio:false,video:{facingMode:{ideal:"environment"},width:{ideal:1920},height:{ideal:1080}}}]);
await runTimer();
assert.equal(frames.length,1);
assert.equal(frames[0].width,1600);
assert.equal(frames[0].height,1200);
assert.equal(captures.length,1);
assert.equal(captures[0].canvas.width,2400);
assert.equal(captures[0].canvas.height,1800);
assert.equal(captures[0].result,detection);
assert.notEqual(captures[0].canvas,frames[0]);
assert.equal(streams[0].videoTrack.stopped,1);
assert.equal(streams[0].otherTrack.stopped,1);
assert.equal(item.video.srcObject,null);
assert.equal(timers.size,0);
assert.equal(await item.camera.capture(),false);
assert.equal(item.errors.length,0);
""")

    def test_auto_capture_keeps_the_original_frame_even_if_video_moves_during_ocr(self):
        self.run_camera(r"""
const delayed=deferred();
const item=setup({onFrame:async canvas=>{item.frames.push(canvas);return delayed.promise;}});
await item.camera.start();await runTimer();
assert.equal(item.frames.length,1);
const recognizedStill=item.frames[0].draws[0][0];
assert.equal(recognizedStill.width,2400);assert.equal(recognizedStill.height,1800);
item.video.videoWidth=640;item.video.videoHeight=480;
delayed.resolve({key:"label"});await flush();
assert.equal(item.captures.length,1);
assert.equal(item.captures[0].canvas,recognizedStill,"retain the image that OCR actually examined");
assert.equal(item.captures[0].canvas.width,2400);
assert.equal(streams[0].videoTrack.stopped,1);
""")

    def test_full_resolution_label_analysis_uses_the_same_still_without_downsampling(self):
        self.run_camera(r"""
const item=setup({fullResolution:true,onFrame:async canvas=>{item.frames.push(canvas);return {key:"label"};}});
await item.camera.start();await runTimer();
assert.equal(item.frames.length,1);assert.equal(item.frames[0].width,2400);
assert.equal(item.frames[0].height,1800);
assert.equal(item.captures[0].canvas,item.frames[0],"read and retain exactly the same image");
assert.equal(streams[0].videoTrack.stopped,1);
""")

    def test_recognition_is_sequential_and_canceled_results_cannot_capture(self):
        self.run_camera(r"""
const pending=deferred();let count=0;
const item=setup({onFrame:async()=>{count++;return pending.promise;}});
await item.camera.start();await runTimer();
assert.equal(count,1);assert.equal(timers.size,0);
await flush();assert.equal(count,1);
item.camera.stop();
pending.resolve({key:"too late"});await flush();
assert.equal(item.captures.length,0);assert.equal(timers.size,0);
assert.equal(item.video.srcObject,null);
assert.equal(streams[0].videoTrack.stopped,1);
""")

    def test_manual_capture_stops_preview_then_waits_for_ocr_before_callback(self):
        self.run_camera(r"""
const pending=deferred();let recognizing=false;const captures=[];
const item=setup({onFrame:async()=>{recognizing=true;const value=await pending.promise;recognizing=false;return value;},
  onCapture:async(canvas,detection)=>{assert.equal(recognizing,false);captures.push({canvas,detection});}});
await item.camera.start();await runTimer();
const capture=item.camera.capture();
assert.equal(streams[0].videoTrack.stopped,1,"manual shutter releases the camera immediately");
assert.equal(item.video.srcObject,null);assert.equal(captures.length,0);
assert.equal(await item.camera.capture(),false);
pending.resolve({key:"automatic result must lose to manual capture"});
assert.equal(await capture,true);
assert.equal(captures.length,1);assert.equal(captures[0].detection,null);
assert.equal(captures[0].canvas.width,2400);assert.equal(timers.size,0);
""")

    def test_pending_permission_cancel_and_restart_release_only_old_stream(self):
        self.run_camera(r"""
acquisition=deferred();const oldAcquisition=acquisition;
const item=setup();
const oldStart=item.camera.start();
assert.equal(item.camera.start(),oldStart,"double start shares one permission request");
assert.equal(requests.length,1);
item.camera.stop();
acquisition=null;
assert.equal(await item.camera.start(),true);
const newStream=streams[0];
const lateStream=makeStream();oldAcquisition.resolve(lateStream);
assert.equal(await oldStart,false);
assert.equal(lateStream.videoTrack.stopped,1);
assert.equal(lateStream.otherTrack.stopped,1);
assert.equal(newStream.videoTrack.stopped,0);
assert.equal(item.video.srcObject,newStream);assert.equal(item.video.plays,1);
item.camera.stop();assert.equal(newStream.videoTrack.stopped,1);
assert.equal(item.errors.length,0);
""")

    def test_stop_while_video_play_is_pending_cannot_restart_preview(self):
        self.run_camera(r"""
const play=deferred(),preview=video();preview.play=()=>play.promise;
const item=setup({video:preview});const starting=item.camera.start();await flush();
assert.equal(preview.srcObject,streams[0]);
item.camera.stop();play.resolve();
assert.equal(await starting,false);assert.equal(preview.srcObject,null);
assert.equal(timers.size,0);assert.ok(streams[0].videoTrack.stopped>=1);
assert.equal(item.captures.length,0);
""")

    def test_insecure_unsupported_and_denied_access_offer_photo_fallback(self):
        self.run_camera(r"""
isSecureContext=false;
const insecure=setup();assert.equal(await insecure.camera.start(),false);
assert.equal(requests.length,0);assert.match(insecure.errors[0].message,/HTTPS.*Take photo/);
isSecureContext=true;
const mediaDevices=navigator.mediaDevices;navigator.mediaDevices=undefined;
const unsupported=setup();assert.equal(await unsupported.camera.start(),false);
assert.match(unsupported.errors[0].message,/doesn't support.*Take photo/);
navigator.mediaDevices=mediaDevices;acquisition=deferred();
const denied=setup();const start=denied.camera.start();
acquisition.reject(Object.assign(new Error("browser details"),{name:"NotAllowedError"}));
assert.equal(await start,false);assert.match(denied.errors[0].message,/denied.*Allow camera/);
assert.equal(denied.errors.length,1);assert.equal(timers.size,0);
""")

    def test_pagehide_and_hidden_pages_release_active_and_pending_camera(self):
        self.run_camera(r"""
const first=setup();await first.camera.start();
windowEvents.fire("pagehide");assert.equal(first.video.srcObject,null);
assert.equal(streams[0].videoTrack.stopped,1);assert.equal(timers.size,0);
acquisition=deferred();const second=setup();const start=second.camera.start();
document.hidden=true;document.fire("visibilitychange");
const lateStream=makeStream();acquisition.resolve(lateStream);
assert.equal(await start,false);assert.equal(lateStream.videoTrack.stopped,1);
assert.equal(second.captures.length,0);assert.equal(second.errors.length,0);
assert.equal(document.listeners.get("visibilitychange").size,0);
assert.equal(windowEvents.listeners.get("pagehide").size,0);
""")

    def test_stopping_during_manual_capture_wait_suppresses_delivery(self):
        self.run_camera(r"""
const pending=deferred();const item=setup({onFrame:()=>pending.promise});
await item.camera.start();await runTimer();
const capture=item.camera.capture();item.camera.stop();
pending.resolve({key:"barcode"});assert.equal(await capture,false);
assert.equal(item.captures.length,0);assert.equal(item.errors.length,0);
assert.equal(timers.size,0);
""")

    def test_current_scan_invalidation_releases_tracks_and_suppresses_errors(self):
        self.run_camera(r"""
const pending=deferred();const item=setup({onFrame:()=>pending.promise});
await item.camera.start();await runTimer();item.valid=false;
pending.reject(new Error("stale OCR error"));await flush();
assert.equal(item.video.srcObject,null);assert.equal(streams[0].videoTrack.stopped,1);
assert.equal(item.errors.length,0);assert.equal(item.captures.length,0);
""")

    def test_track_end_and_recognition_errors_release_the_camera(self):
        self.run_camera(r"""
const ended=setup();await ended.camera.start();streams[0].videoTrack.fire("ended");
assert.equal(ended.errors.length,1);assert.match(ended.errors[0].message,/camera stopped/);
assert.equal(ended.video.srcObject,null);assert.equal(timers.size,0);
const failed=setup({onFrame:async()=>{throw new Error("Label reader failed");}});
await failed.camera.start();await runTimer();
assert.equal(failed.errors.length,1);assert.equal(failed.errors[0].message,"Label reader failed");
assert.equal(streams[1].videoTrack.stopped,1);assert.equal(failed.video.srcObject,null);
""")

    def test_portrait_and_small_video_preserve_dimensions_without_upscaling(self):
        self.run_camera(r"""
const tall=setup({video:video(1080,1920)});await tall.camera.start();
await runTimer();assert.equal(tall.frames[0].width,900);assert.equal(tall.frames[0].height,1600);
assert.equal(await tall.camera.capture(),true);
assert.equal(tall.captures[0].canvas.width,1080);assert.equal(tall.captures[0].canvas.height,1920);
const small=setup({video:video(640,480)});await small.camera.start();await runTimer();
assert.equal(small.frames[0].width,640);assert.equal(small.frames[0].height,480);
small.camera.stop();
""")

    def test_restart_waits_for_previous_recognition_without_overlapping_workers(self):
        self.run_camera(r"""
const pending=deferred();let jobs=0,concurrency=0;
const item=setup({onFrame:async()=>{
  jobs++;concurrency++;assert.equal(concurrency,1);
  if(jobs===1)await pending.promise;
  concurrency--;return null;
}});
await item.camera.start();await runTimer();assert.equal(jobs,1);
item.camera.stop();await item.camera.start();await runTimer();
assert.equal(jobs,1,"the restarted scan must wait for the old worker job");
pending.resolve(null);await flush();assert.equal(jobs,2);assert.equal(timers.size,1);
item.camera.stop();
""")

    def test_manual_shutter_waits_for_a_readable_frame_without_claiming_capture(self):
        self.run_camera(r"""
const preview=video();preview.readyState=1;
const item=setup({video:preview});await item.camera.start();
assert.equal(await item.camera.capture(),false);
assert.equal(item.captures.length,0);assert.equal(streams[0].videoTrack.stopped,0);
assert.match(item.statuses.at(-1),/still starting/);
await runTimer();assert.equal(item.frames.length,0);assert.equal(timers.size,1);
preview.readyState=4;
assert.equal(await item.camera.capture(),true);assert.equal(item.captures.length,1);
assert.equal(streams[0].videoTrack.stopped,1);assert.equal(timers.size,0);
""")

    def test_playback_failure_cleans_acquired_tracks_and_reports_once(self):
        self.run_camera(r"""
const preview=video();preview.play=async()=>{throw Object.assign(new Error("camera busy"),{name:"NotReadableError"});};
const item=setup({video:preview});assert.equal(await item.camera.start(),false);
assert.equal(item.errors.length,1);assert.match(item.errors[0].message,/camera is busy/);
assert.equal(streams[0].videoTrack.stopped,1);assert.equal(streams[0].otherTrack.stopped,1);
assert.equal(preview.srcObject,null);assert.equal(timers.size,0);
""")
