'use strict';
const $=id=>document.getElementById(id), form=$('parameters');
const colors={RED:'#ff6277',YELLOW:'#ffbc60',GREEN:'#45deba'};
const pending=new Map(); let socket=null,current=null,dirty=false,request=0,online=false;
const conversion={desired_speed:3.6,left_ratio:100,right_ratio:100};
// Preserve valid SI-to-display fractions (13.9 m/s is exactly 50.04 km/h).
for(const input of form.querySelectorAll('input[type="number"]'))
  if(!['seed','max_vehicles','initial_queue'].includes(input.name))input.step='any';
let junction=null;
fetch('/api/junction').then(r=>r.json()).then(j=>{junction=j;$('junction-name').textContent=j.name;for(const arm of j.arms)$('approaches').insertAdjacentHTML('beforeend',`<div class="approach"><span><i class="dot" id="dot-${arm.id}"></i>${arm.id} · ${arm.name.toUpperCase()}</span><strong id="queue-${arm.id}">—</strong><small> queued</small><span class="meta" id="length-${arm.id}">— m</span><span class="meta" id="demand-${arm.id}">— veh/h</span></div>`);if(current)render(current,true);}).catch(error=>showError(`Junction geometry unavailable: ${error.message}`));
function showError(message){$('error').textContent=message;$('error').hidden=!message;}
function controls(){const busy=pending.size>0;for(const b of document.querySelectorAll('button'))b.disabled=!online||busy;if(!online||busy)return;const m=current?.mode;$('start').disabled=m!=='stopped';$('pause').disabled=m!=='running';$('resume').disabled=m!=='paused';$('stop').disabled=m==='stopped';}
function populate(p){for(const input of form.elements){if(!input.name)continue;const value=p[input.name];if(input.type==='checkbox'){input.checked=value;continue;}input.value=typeof value==='number'?Number((value*(conversion[input.name]||1)).toFixed(5)):value;}}
function render(s,force){if(!force&&current&&current.session_id===s.session_id&&s.sequence<current.sequence)return;current=s;const m=s.metrics,signals=s.signals;$('clock').innerHTML=`${s.timestamp.toFixed(1)} <small>s</small>`;$('mode').textContent=s.mode;$('mode').className='badge'+(s.mode==='running'?' live':'');$('phase').textContent=signals.stage.replaceAll('_',' ');$('remaining').textContent=`${signals.remaining.toFixed(1)} s`;$('phase-progress').style.width=`${100*signals.remaining/Math.max(.01,signals.elapsed+signals.remaining)}%`;$('queued').textContent=m.queue_total;$('wait').innerHTML=`${m.mean_wait.toFixed(1)} <small>s</small>`;$('completed').textContent=m.completed;$('speed').innerHTML=`${(m.mean_speed*3.6).toFixed(1)} <small>km/h</small>`;$('active').textContent=`${m.active_vehicles} active · ${m.blocked_arrivals} blocked arrivals`;$('throughput').textContent=`${m.throughput_vph.toFixed(0)} vehicles / hour`;$('reservation').textContent=`Conflict-zone reservations · ${m.box_occupants.length?`${m.box_occupants.length} committed (compatible movements only)`:'clear'} · committed vehicles may finish during clearance`;const clock=m.clock_hour,hh=Math.floor(clock),mm=Math.floor((clock-hh)*60);$('context').textContent=`Local time ${String(hh).padStart(2,'0')}:${String(mm).padStart(2,'0')} · demand ${s.parameters.demand_mode} · ${m.pcu_throughput_pch.toFixed(0)} PCU/h discharged · cycle ${s.signals.cycle.toFixed(0)} s${m.edge_queue?` · ${m.edge_queue} waiting to enter`:''}${liveText()}`;for(const[a,q]of Object.entries(m.approaches)){if(!$(`queue-${a}`))continue;$(`demand-${a}`).textContent=`${m.demand_vph[a].toFixed(0)} veh/h arriving`;$(`queue-${a}`).textContent=q.queue_count;$(`length-${a}`).textContent=`${q.queue_length_m.toFixed(1)} m longest lane`;$(`dot-${a}`).style.background=colors[signals.groups[a]];}$('sync').textContent=`${s.session_id.slice(0,8)} / state ${s.sequence}`;if(!dirty)populate(s.parameters);drawMap(s);controls();}
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
function offsetLine(points,d){return points.map((p,i)=>{const a=points[Math.max(0,i-1)],b=points[Math.min(points.length-1,i+1)],len=Math.hypot(b[0]-a[0],b[1]-a[1])||1;return [p[0]-(b[1]-a[1])/len*d,p[1]+(b[0]-a[0])/len*d];});}
function at(points,s){let t=0;for(let i=1;i<points.length;i++){const a=points[i-1],b=points[i],l=Math.hypot(b[0]-a[0],b[1]-a[1]);if(t+l>=s)return[a[0]+(b[0]-a[0])*(s-t)/l,a[1]+(b[1]-a[1])*(s-t)/l];t+=l;}return points.at(-1);}
function slice(points,from){const out=[at(points,from)];let t=0;for(let i=1;i<points.length;i++){t+=Math.hypot(points[i][0]-points[i-1][0],points[i][1]-points[i-1][1]);if(t>from)out.push(points[i]);}return out;}
function strip(ctx,points,a,b){const left=offsetLine(points,a),right=offsetLine(points,b).reverse();ctx.beginPath();[...left,...right].forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();ctx.fill();}
function line(ctx,points){ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.stroke();}
function drawMap(s){const canvas=$('map'),ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height;ctx.clearRect(0,0,w,h);if(!junction)return;
const extent=Math.max(...junction.arms.map(a=>a.extent))+6,scale=Math.min(w,h)/(2*extent);ctx.save();ctx.translate(w/2,h/2);ctx.scale(scale,-scale);
ctx.fillStyle='#182f35';ctx.fillRect(-extent,-extent,2*extent,2*extent);ctx.fillStyle='#22404a';
for(const b of junction.buildings){ctx.beginPath();b.footprint.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();ctx.fill();}
const lhs=junction.driving_side==='left'?1:-1;
for(const arm of junction.arms){const m=arm.median/2,inW=arm.in_lanes*arm.lane_width,outW=arm.out_lanes*arm.lane_width;ctx.fillStyle='#4a5a66';strip(ctx,arm.axis,lhs*(m+outW+2.5),-lhs*(m+inW+2.5));ctx.fillStyle='#283747';strip(ctx,arm.axis,lhs*(m+outW),-lhs*(m+inW));}
ctx.fillStyle='#283747';ctx.beginPath();junction.box.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.closePath();ctx.fill();
for(const arm of junction.arms){const m=arm.median/2,beyond=slice(arm.axis,arm.stop);ctx.fillStyle='#6d7f6a';strip(ctx,beyond,m,-m);ctx.strokeStyle='#70899b';ctx.lineWidth=.15;ctx.setLineDash([3,3]);
for(let k=1;k<arm.in_lanes;k++)line(ctx,offsetLine(beyond,-lhs*(m+k*arm.lane_width)));for(let k=1;k<arm.out_lanes;k++)line(ctx,offsetLine(beyond,lhs*(m+k*arm.lane_width)));ctx.setLineDash([]);
const p=at(arm.axis,arm.stop),q=at(arm.axis,arm.stop+1),dx=q[0]-p[0],dy=q[1]-p[1],nx=-dy*lhs,ny=dx*lhs;ctx.strokeStyle='#ecf3ee';ctx.lineWidth=.5;ctx.beginPath();ctx.moveTo(p[0]-nx*m,p[1]-ny*m);ctx.lineTo(p[0]-nx*(m+arm.in_lanes*arm.lane_width),p[1]-ny*(m+arm.in_lanes*arm.lane_width));ctx.stroke();
const sx=p[0]-nx*(m+arm.in_lanes*arm.lane_width+1.8),sy=p[1]-ny*(m+arm.in_lanes*arm.lane_width+1.8);ctx.fillStyle='#07121c';ctx.beginPath();ctx.arc(sx,sy,2.2,0,Math.PI*2);ctx.fill();ctx.fillStyle=colors[s.signals.groups[arm.id]];ctx.beginPath();ctx.arc(sx,sy,1.4,0,Math.PI*2);ctx.fill();}
const widths={car:1.75,bus:2.6,truck:2.3,motorcycle:.75,auto:1.4},fills={car:'#62b5df',bus:'#edb850',truck:'#74c8a6',motorcycle:'#ce79ba',auto:'#d9e35a'};
for(const v of Object.values(s.vehicles)){const width=widths[v.type];ctx.save();ctx.translate(v.position[0],v.position[1]);ctx.rotate(v.heading);ctx.fillStyle=fills[v.type];ctx.fillRect(-width/2,-v.length/2,width,v.length);ctx.restore();}
ctx.restore();ctx.fillStyle='#7e9eae';ctx.font='bold 13px system-ui';ctx.textAlign='center';
for(const arm of junction.arms){const p=at(arm.axis,arm.extent-12);ctx.fillText(`${arm.id} · ${arm.name}`,w/2+p[0]*scale,h/2-p[1]*scale);}}
function drawChart(samples){const c=$('chart'),ctx=c.getContext('2d'),left=36,right=c.width-40,top=18,bottom=c.height-20;ctx.clearRect(0,0,c.width,c.height);const maxQueue=Math.max(10,...samples.map(s=>s.queue)),maxWait=Math.max(30,...samples.map(s=>s.mean_wait));ctx.font='10px monospace';for(let i=0;i<4;i++){const y=top+(bottom-top)*i/3;ctx.strokeStyle='#293d4d';ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();ctx.fillStyle='#45deba';ctx.fillText((maxQueue*(1-i/3)).toFixed(0),2,y+3);ctx.fillStyle='#ffbc60';ctx.fillText(`${(maxWait*(1-i/3)).toFixed(0)}s`,right+6,y+3);}if(!samples.length)return;const start=samples[0].timestamp,end=samples.at(-1).timestamp,span=Math.max(.1,end-start);for(const[field,max,color]of [['queue',maxQueue,'#45deba'],['mean_wait',maxWait,'#ffbc60']]){ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();samples.forEach((s,i)=>{const x=left+(s.timestamp-start)/span*(right-left),y=bottom-s[field]/max*(bottom-top);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();}$('history-start').textContent=`${start.toFixed(0)} s`;$('history-end').textContent=`${end.toFixed(0)} s`;}
controls();connect();
