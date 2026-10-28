'use strict';
const $=id=>document.getElementById(id), form=$('parameters');
const colors={RED:'#ff6277',YELLOW:'#ffbc60',GREEN:'#45deba'};
const pending=new Map(); let socket=null,current=null,dirty=false,request=0,online=false;
const conversion={desired_speed:3.6,left_ratio:100,right_ratio:100};
// Preserve valid SI-to-display fractions (13.9 m/s is exactly 50.04 km/h).
for(const input of form.querySelectorAll('input[type="number"]'))
  if(!['seed','max_vehicles','initial_queue'].includes(input.name))input.step='any';
let junction=null;
fetch('/api/junction').then(r=>r.json()).then(j=>{junction=j;TwinMap.setJunction(j);$('junction-name').textContent=j.name;for(const arm of j.arms)$('approaches').insertAdjacentHTML('beforeend',`<div class="approach"><span><i class="dot" id="dot-${arm.id}"></i>${arm.id} · ${arm.name.toUpperCase()}</span><strong id="queue-${arm.id}">—</strong><small> queued</small><span class="meta" id="length-${arm.id}">— m</span><span class="meta" id="demand-${arm.id}">— veh/h</span></div>`);if(current)render(current,true);}).catch(error=>showError(`Junction geometry unavailable: ${error.message}`));
function showError(message){$('error').textContent=message;$('error').hidden=!message;}
function controls(){const busy=pending.size>0;for(const b of document.querySelectorAll('button'))b.disabled=!online||busy;if(!online||busy)return;const m=current?.mode;$('start').disabled=m!=='stopped';$('pause').disabled=m!=='running';$('resume').disabled=m!=='paused';$('stop').disabled=m==='stopped';}
function populate(p){for(const input of form.elements){if(!input.name)continue;const value=p[input.name];if(input.type==='checkbox'){input.checked=value;continue;}input.value=typeof value==='number'?Number((value*(conversion[input.name]||1)).toFixed(5)):value;}}
function render(s,force){if(!force&&current&&current.session_id===s.session_id&&s.sequence<current.sequence)return;current=s;const m=s.metrics,signals=s.signals;$('clock').innerHTML=`${s.timestamp.toFixed(1)} <small>s</small>`;$('mode').textContent=s.mode;$('mode').className='badge'+(s.mode==='running'?' live':'');$('phase').textContent=signals.stage.replaceAll('_',' ');$('remaining').textContent=`${signals.remaining.toFixed(1)} s`;$('phase-progress').style.width=`${100*signals.remaining/Math.max(.01,signals.elapsed+signals.remaining)}%`;$('queued').textContent=m.queue_total;$('wait').innerHTML=`${m.mean_wait.toFixed(1)} <small>s</small>`;$('completed').textContent=m.completed;$('speed').innerHTML=`${(m.mean_speed*3.6).toFixed(1)} <small>km/h</small>`;$('active').textContent=`${m.active_vehicles} active · ${m.blocked_arrivals} blocked arrivals`;$('throughput').textContent=`${m.throughput_vph.toFixed(0)} vehicles / hour`;$('reservation').textContent=`Conflict-zone reservations · ${m.box_occupants.length?`${m.box_occupants.length} committed (compatible movements only)`:'clear'} · committed vehicles may finish during clearance`;const clock=m.clock_hour,hh=Math.floor(clock),mm=Math.floor((clock-hh)*60);$('context').textContent=`Local time ${String(hh).padStart(2,'0')}:${String(mm).padStart(2,'0')} · demand ${s.parameters.demand_mode} · ${m.pcu_throughput_pch.toFixed(0)} PCU/h discharged · cycle ${s.signals.cycle.toFixed(0)} s${m.edge_queue?` · ${m.edge_queue} waiting to enter`:''}${liveText()}`;for(const[a,q]of Object.entries(m.approaches)){if(!$(`queue-${a}`))continue;$(`demand-${a}`).textContent=`${m.demand_vph[a].toFixed(0)} veh/h arriving`;$(`queue-${a}`).textContent=q.queue_count;$(`length-${a}`).textContent=`${q.queue_length_m.toFixed(1)} m longest lane`;$(`dot-${a}`).style.background=colors[signals.groups[a]];}$('sync').textContent=`${s.session_id.slice(0,8)} / state ${s.sequence}`;if(!dirty)populate(s.parameters);TwinMap.update(s);controls();}
function command(action,parameters){if(!online||pending.size)return;const id=`ui-${++request}`;showError('');const timer=setTimeout(()=>{pending.delete(id);showError('Command response timed out. Inspect live state before retrying.');controls();},4000);pending.set(id,{timer,action});socket.send(JSON.stringify({type:'command',request_id:id,action,...(parameters?{parameters}:{})}));controls();}
document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>command(b.dataset.action)));
form.addEventListener('input',()=>{dirty=true;$('applied').textContent='Unsaved changes';});
form.addEventListener('submit',event=>{event.preventDefault();if(!form.reportValidity())return;const p={};for(const input of form.elements){if(!input.name)continue;p[input.name]=input.type==='checkbox'?input.checked:input.tagName==='SELECT'?input.value:Number(input.value)/(conversion[input.name]||1);}command('parameters',p);});
let receivedAt=Date.now();
function disconnected(ws){
  if(ws!==socket)return;
  socket=null;online=false;
  $('connection').textContent='Offline · reconnecting';$('connection').className='badge offline';
  $('blender').textContent='Blender · unknown';$('blender').className='badge offline';
  for(const item of pending.values())clearTimeout(item.timer);
  if(pending.size)showError('Connection lost during a command. Inspect state before retrying.');
  pending.clear();controls();setTimeout(connect,1000);
}
function connect(){
  const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);
  socket=ws;
  ws.onopen=()=>{
    if(socket!==ws){ws.close();return;}
    receivedAt=Date.now();online=true;
    $('connection').textContent='● WebSocket online';$('connection').className='badge live';controls();
  };
  ws.onmessage=event=>{
    if(socket!==ws)return;
    receivedAt=Date.now();
    try{
      const message=JSON.parse(event.data);
      if(message.type==='state'){
        render(message.state);
        const live=message.health?.blender_connected,missing=message.health?.blender?.missing_signals?.length;
        $('blender').textContent=live?(missing?'Blender · missing signals':'● Blender synchronized'):'Blender · disconnected';
        $('blender').className='badge'+(live&&!missing?' live':' offline');
        if(message.history)drawChart(message.history);liveFeed=message.health?.live||null;
      }else if(message.type==='ack'||message.type==='error'){
        const item=pending.get(message.request_id);
        if(item){
          clearTimeout(item.timer);pending.delete(message.request_id);
          if(message.type==='error')showError(message.error);
          else if(item.action==='parameters'){dirty=false;$('applied').textContent=`Applied / state ${message.sequence}`;}
        }
        controls();
      }
    }catch(error){showError(`Invalid server message: ${error.message}`);}
  };
  ws.onclose=()=>disconnected(ws);
  ws.onerror=()=>{disconnected(ws);ws.close();};
}
setInterval(()=>{
  if(online&&socket&&Date.now()-receivedAt>4000){const ws=socket;disconnected(ws);ws.close();}
},1000);

let liveFeed=null;
function liveText(){if(!liveFeed||current?.parameters.demand_mode!=='live')return '';return ` · live: ${liveFeed.message}${liveFeed.updated?` (${Math.round(Date.now()/1000-liveFeed.updated)} s ago)`:''}`;}
function drawChart(samples){const c=$('chart'),ctx=c.getContext('2d'),left=36,right=c.width-40,top=18,bottom=c.height-20;ctx.clearRect(0,0,c.width,c.height);const maxQueue=Math.max(10,...samples.map(s=>s.queue)),maxWait=Math.max(30,...samples.map(s=>s.mean_wait));ctx.font='10px monospace';for(let i=0;i<4;i++){const y=top+(bottom-top)*i/3;ctx.strokeStyle='#293d4d';ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();ctx.fillStyle='#45deba';ctx.fillText((maxQueue*(1-i/3)).toFixed(0),2,y+3);ctx.fillStyle='#ffbc60';ctx.fillText(`${(maxWait*(1-i/3)).toFixed(0)}s`,right+6,y+3);}if(!samples.length)return;const start=samples[0].timestamp,end=samples.at(-1).timestamp,span=Math.max(.1,end-start);for(const[field,max,color]of [['queue',maxQueue,'#45deba'],['mean_wait',maxWait,'#ffbc60']]){ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();samples.forEach((s,i)=>{const x=left+(s.timestamp-start)/span*(right-left),y=bottom-s[field]/max*(bottom-top);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();}$('history-start').textContent=`${start.toFixed(0)} s`;$('history-end').textContent=`${end.toFixed(0)} s`;}
controls();connect();
