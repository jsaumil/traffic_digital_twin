'use strict';
const $=id=>document.getElementById(id), form=$('parameters');
const colors={RED:'#ff6277',YELLOW:'#ffbc60',GREEN:'#45deba'};
const pending=new Map(); let socket=null,current=null,dirty=false,request=0,online=false;
const conversion={desired_speed:3.6,left_ratio:100,right_ratio:100};
// Preserve valid SI-to-display fractions (13.9 m/s is exactly 50.04 km/h).
for(const input of form.querySelectorAll('input[type="number"]'))
  if(!['seed','max_vehicles','initial_queue'].includes(input.name))input.step='any';
for(const a of ['N','S','E','W']) $('approaches').insertAdjacentHTML('beforeend',`<div class="approach"><span><i class="dot" id="dot-${a}"></i>${a} APPROACH</span><strong id="queue-${a}">—</strong><small> queued</small><span class="meta" id="length-${a}">— m</span></div>`);
function showError(message){$('error').textContent=message;$('error').hidden=!message;}
function controls(){const busy=pending.size>0;for(const b of document.querySelectorAll('button'))b.disabled=!online||busy;if(!online||busy)return;const m=current?.mode;$('start').disabled=m!=='stopped';$('pause').disabled=m!=='running';$('resume').disabled=m!=='paused';$('stop').disabled=m==='stopped';}
function populate(p){for(const input of form.elements){if(!input.name)continue;const value=p[input.name];input.value=typeof value==='number'?Number((value*(conversion[input.name]||1)).toFixed(5)):value;}}
function render(s){if(current&&current.session_id===s.session_id&&s.sequence<current.sequence)return;current=s;const m=s.metrics,signals=s.signals;$('clock').innerHTML=`${s.timestamp.toFixed(1)} <small>s</small>`;$('mode').textContent=s.mode;$('mode').className='badge'+(s.mode==='running'?' live':'');$('phase').textContent=signals.stage.replaceAll('_',' ');$('remaining').textContent=`${signals.remaining.toFixed(1)} s`;$('phase-progress').style.width=`${100*signals.remaining/Math.max(.01,signals.elapsed+signals.remaining)}%`;$('queued').textContent=m.queue_total;$('wait').innerHTML=`${m.mean_wait.toFixed(1)} <small>s</small>`;$('completed').textContent=m.completed;$('speed').innerHTML=`${(m.mean_speed*3.6).toFixed(1)} <small>km/h</small>`;$('active').textContent=`${m.active_vehicles} active · ${m.blocked_arrivals} blocked arrivals`;$('throughput').textContent=`${m.throughput_vph.toFixed(0)} vehicles / hour`;$('reservation').textContent=`Conflict-zone reservation · ${m.reservation_owner||'clear'} · already committed vehicles may finish during clearance`;for(const[a,q]of Object.entries(m.approaches)){$(`queue-${a}`).textContent=q.queue_count;$(`length-${a}`).textContent=`${q.queue_length_m.toFixed(1)} m longest lane`;$(`dot-${a}`).style.background=colors[signals.groups[a]];}$('sync').textContent=`${s.session_id.slice(0,8)} / state ${s.sequence}`;if(!dirty)populate(s.parameters);drawMap(s);controls();}
function command(action,parameters){if(!online||pending.size)return;const id=`ui-${++request}`;showError('');const timer=setTimeout(()=>{pending.delete(id);showError('Command response timed out. Inspect live state before retrying.');controls();},4000);pending.set(id,{timer,action});socket.send(JSON.stringify({type:'command',request_id:id,action,...(parameters?{parameters}:{})}));controls();}
document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>command(b.dataset.action)));
form.addEventListener('input',()=>{dirty=true;$('applied').textContent='Unsaved changes';});
form.addEventListener('submit',event=>{event.preventDefault();if(!form.reportValidity())return;const p={};for(const[name,value]of new FormData(form))p[name]=name==='yellow_policy'?value:Number(value)/(conversion[name]||1);command('parameters',p);});
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
        if(message.history)drawChart(message.history);
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

function drawMap(s){const canvas=$('map'),ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height;ctx.clearRect(0,0,w,h);const scale=Math.min(w,h)/148;ctx.save();ctx.translate(w/2,h/2);ctx.scale(scale,-scale);ctx.fillStyle='#182f35';ctx.fillRect(-74,-74,148,148);ctx.fillStyle='#283747';ctx.fillRect(-6.4,-74,12.8,148);ctx.fillRect(-74,-6.4,148,12.8);ctx.fillRect(-11,-11,22,22);ctx.strokeStyle='#70899b';ctx.lineWidth=.12;ctx.setLineDash([3,3]);for(const offset of [-3.2,3.2]){ctx.beginPath();ctx.moveTo(offset,-72);ctx.lineTo(offset,-11);ctx.moveTo(offset,11);ctx.lineTo(offset,72);ctx.moveTo(-72,offset);ctx.lineTo(-11,offset);ctx.moveTo(11,offset);ctx.lineTo(72,offset);ctx.stroke();}ctx.setLineDash([]);ctx.strokeStyle='#e6ba57';ctx.lineWidth=.15;for(const sign of [-1,1]){ctx.beginPath();ctx.moveTo(0,sign*11);ctx.lineTo(0,sign*73);ctx.moveTo(sign*11,0);ctx.lineTo(sign*73,0);ctx.stroke();}ctx.strokeStyle='#ecf3ee';ctx.lineWidth=.45;for(const[x,y,dx,dy]of [[0,11,-6.4,0],[0,-11,6.4,0],[11,0,0,6.4],[-11,0,0,-6.4]]){ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+dx,y+dy);ctx.stroke();}for(const v of Object.values(s.vehicles)){const width={car:1.85,bus:2.5,truck:2.4,motorcycle:.8}[v.type];ctx.save();ctx.translate(v.position[0],v.position[1]);ctx.rotate(v.heading);ctx.fillStyle={car:'#62b5df',bus:'#edb850',truck:'#74c8a6',motorcycle:'#ce79ba'}[v.type];ctx.fillRect(-width/2,-v.length/2,width,v.length);ctx.fillStyle='#dceff4';ctx.fillRect(-width*.38,v.length*.13,width*.76,v.length*.17);ctx.restore();}for(const[a,x,y]of [['N',-8.5,12],['S',8.5,-12],['E',12,8.5],['W',-12,-8.5]]){ctx.fillStyle='#07121c';ctx.beginPath();ctx.arc(x,y,1.45,0,Math.PI*2);ctx.fill();ctx.fillStyle=colors[s.signals.groups[a]];ctx.beginPath();ctx.arc(x,y,.85,0,Math.PI*2);ctx.fill();}ctx.restore();ctx.fillStyle='#7e9eae';ctx.font='bold 14px system-ui';ctx.textAlign='center';ctx.fillText('N',w/2,20);ctx.fillText('S',w/2,h-7);ctx.fillText('W',w/2-72*scale, h/2-16);ctx.fillText('E',w/2+72*scale,h/2-16);}
function drawChart(samples){const c=$('chart'),ctx=c.getContext('2d'),left=36,right=c.width-40,top=18,bottom=c.height-20;ctx.clearRect(0,0,c.width,c.height);const maxQueue=Math.max(10,...samples.map(s=>s.queue)),maxWait=Math.max(30,...samples.map(s=>s.mean_wait));ctx.font='10px monospace';for(let i=0;i<4;i++){const y=top+(bottom-top)*i/3;ctx.strokeStyle='#293d4d';ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();ctx.fillStyle='#45deba';ctx.fillText((maxQueue*(1-i/3)).toFixed(0),2,y+3);ctx.fillStyle='#ffbc60';ctx.fillText(`${(maxWait*(1-i/3)).toFixed(0)}s`,right+6,y+3);}if(!samples.length)return;const start=samples[0].timestamp,end=samples.at(-1).timestamp,span=Math.max(.1,end-start);for(const[field,max,color]of [['queue',maxQueue,'#45deba'],['mean_wait',maxWait,'#ffbc60']]){ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();samples.forEach((s,i)=>{const x=left+(s.timestamp-start)/span*(right-left),y=bottom-s[field]/max*(bottom-top);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();}$('history-start').textContent=`${start.toFixed(0)} s`;$('history-end').textContent=`${end.toFixed(0)} s`;}
controls();connect();
