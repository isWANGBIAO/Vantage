const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { EventEmitter } = require('node:events');
const { Application } = require('./application.cjs');
async function fixture(t, reconcileStartup) {
  const dataDir = await fs.mkdtemp(path.join(os.tmpdir(), 'never-stop-startup-app-'));
  t.after(() => fs.rm(dataDir, {recursive:true, force:true}));
  await fs.writeFile(path.join(dataDir,'settings.json'), JSON.stringify({launchAtLogin:true, notificationTime:'10:30'}));
  const runner = new EventEmitter(); runner.snapshot = () => [{id:'kept',totalRunMs:123456}];
  return new Application({dataDir,runner,resources:{list:()=>[]},reconcileStartup,appVersion:'1.0.79'});
}
test('loading saved settings reconciles enabled startup with the running version and keeps project data',async t=>{
  const calls=[]; const app=await fixture(t, settings=>calls.push({...settings}));
  await app.init(); assert.equal(calls.length,1); assert.equal(calls[0].launchAtLogin,true);
  const state=await app.invoke('state'); assert.equal(state.appVersion,'1.0.79'); assert.equal(state.projects[0].totalRunMs,123456); assert.equal(state.settings.notificationTime,'10:30');
});
test('startup reconciliation failure is visible without preventing application startup',async t=>{
  const app=await fixture(t,()=>{throw Error('fixture registry unavailable');});
  await app.init(); const state=await app.invoke('state'); assert.match(state.settings.startupError,/fixture registry unavailable/); assert.equal(state.settings.launchAtLogin,true);
  app.applySettings=async()=>{};
  await app.invoke('settings.save',{settings:{launchAtLogin:false}});
  assert.equal((await app.invoke('state')).settings.startupError,undefined);
});
