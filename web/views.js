/* Safe DOM renderers for the seven local dashboard tabs. */
const UI={
 escape(v){return String(v??"").replace(/[&<>"']/g,c=>({
  "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));},
 all(){this.dashboard();this.targets();this.profiles();this.logs();this.game();},
 dashboard(){
  const s=App.state.status;
  $("status").textContent=s.state||"idle";
  $("stats").innerHTML=[["Целей",s.targets],["Обработано",s.processed],
   ["Профилей",s.profiles],["Ошибок",s.errors]].map(([label,value])=>
    '<div class="stat"><small>'+label+'</small><strong>'+Number(value||0)+'</strong></div>').join("");
  $("progress").value=Number(s.progress||0);
  $("current-target").textContent=s.current_target||"Нет активной задачи";
  $("uptime").textContent="Аптайм: "+Math.floor((s.uptime||0)/60)+" мин.";
 },
 targets(){
  const esc=this.escape;
  $("target-count").textContent=App.state.targets.length+" записей";
  $("target-rows").innerHTML=App.state.targets.map(t=>
   "<tr><td><input type='checkbox' data-select='"+esc(t.id)+"' "+(App.state.selected.has(t.id)?"checked":"")+"></td>"+
   "<td>"+esc(t.value)+"</td><td>"+esc(t.status)+"</td>"+
   "<td class='error'>"+esc(t.error)+"</td><td>"+
   "<button data-action='run' data-id='"+esc(t.id)+"'>Пуск</button> "+
   "<button data-action='edit' data-id='"+esc(t.id)+"'>Изменить</button> "+
   "<button data-action='delete' data-id='"+esc(t.id)+"'>Удалить</button></td></tr>").join("");
 },
 profiles(){
  const search=$("profile-search").value.toLocaleLowerCase();
  const filter=$("profile-filter").value;
  const found=App.state.profiles.filter(p=>(filter!=="conflict"||p.conflicts.length)&&
   JSON.stringify(p).toLocaleLowerCase().includes(search));
  const esc=this.escape;
  $("profile-grid").innerHTML=found.map(p=>{
   const name=p.names[0]||p.id.slice(0,8);
   const desc=[...p.work,...p.interests].slice(0,2).join(", ");
   return "<article class='card'><div class='avatar'>"+esc(name.slice(0,1).toUpperCase())+
    "</div><h2>"+esc(name)+"</h2><p>"+esc(desc||"Публичный профиль")+
    "</p><button data-id='"+esc(p.id)+"'>Полное досье</button></article>";
  }).join("")||"<p class='muted'>Ничего не найдено</p>";
  this.profileDetail();
 },
 profileDetail(){
  const p=App.state.detail;
  $("profile-detail").hidden=!p;
  if(p)$("profile-json").textContent=JSON.stringify(p,null,2);
 },
 logs(){
  const filter=$("log-level").value;
  const search=$("log-search").value.toLocaleLowerCase();
  const matched=App.state.logs.filter(l=>(filter==="ALL"||filter===l.level)&&
    (l.msg||"").toLocaleLowerCase().includes(search)).slice(-800);
  const list=$("log-list");
  list.replaceChildren(...matched.map(l=>{
    const line=document.createElement("div");line.className="log-line";
    const ts=document.createElement("span");ts.className="ts";ts.textContent=l.ts+" ";
    const level=document.createElement("span");level.className=l.level;level.textContent="["+l.level+"] ";
    line.append(ts,level,document.createTextNode(l.msg||""));return line;
  }));
  if($("autoscroll").checked)list.scrollTop=list.scrollHeight;
 },
 game(){
  const s=App.state.status;
  $("game-state").textContent=JSON.stringify(s.game_state||{},null,2);
  $("game-decision").textContent=JSON.stringify(s.last_decision||{},null,2);
 },
 async graph(){
  if(!$("graph").classList.contains("active"))return;
  const canvas=$("graph-canvas");
  try{
    const graph=await App.api("/api/graph");
    if(!window.vis){canvas.textContent="Графическая библиотека недоступна. Узлов: "+graph.nodes.length;return;}
    if(this.network)this.network.destroy();
    this.network=new vis.Network(canvas,{
      nodes:new vis.DataSet(graph.nodes),
      edges:new vis.DataSet(graph.edges.map(edge=>Object.assign({},edge,{
        color:edge.type==="same_person"?"#69baff":"#a3aa81",
        dashes:edge.type==="associate",
        title:edge.type+" - "+edge.weight+" signals"
      })))
    },{autoResize:true,interaction:{hover:true},physics:{stabilization:true},
       nodes:{shape:"dot",size:15,font:{color:"#e8edf7"},color:"#6799fa"},
       edges:{color:"#687d9b",font:{color:"#a8b4ca"}}});
    this.network.on("click",params=>{if(params.nodes.length)App.openProfile(params.nodes[0]);});
  }catch(e){canvas.textContent=e.message;}
 },
 async loadSettings(){
  try{App.state.config=await App.api("/api/config");this.settings();}
  catch(e){App.toast(e.message);}
 },
 settings(){
  const config=App.state.config;
  $("env-fields").innerHTML=Object.entries(config.env||{}).map(([key,value])=>
   '<label class="field"><span>'+this.escape(key)+'</span><input data-env="'+this.escape(key)+
   '" value="'+this.escape(value)+'"></label>').join("");
  $("prompt-fields").innerHTML=Object.entries(config.prompts||{}).map(([key,value])=>
   '<label class="field"><span>'+this.escape(key)+'</span><textarea data-prompt="'+this.escape(key)+
   '" rows="8">'+this.escape(value)+'</textarea></label>').join("");
 }
};
