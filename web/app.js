/* HTTP, state and WebSocket transport. */
const $=id=>document.getElementById(id);
const App={
 token:sessionStorage.getItem("om-token")||"",
 state:{status:{},targets:[],profiles:[],logs:[],config:{},selected:new Set(),detail:null},
 toast(message){const el=$("toast");el.textContent=String(message);el.classList.add("visible");setTimeout(()=>el.classList.remove("visible"),3000);},
 async api(path,options={},retry=true){
  const headers=Object.assign({},options.headers||{});
  if(this.token)headers.Authorization="Bearer "+this.token;
  if(options.body&&typeof options.body!=="string"){
    headers["Content-Type"]="application/json";options.body=JSON.stringify(options.body);
  }
  const res=await fetch(path,Object.assign({},options,{headers}));
  if(res.status===401&&retry){
    const answer=prompt("Токен доступа:");
    if(answer===null)throw Error("Авторизация отменена");
    this.token=answer;sessionStorage.setItem("om-token",answer);
    return this.api(path,options,false);
  }
  if(!res.ok){
    let error="HTTP "+res.status;
    try{error=(await res.json()).detail||error;}catch(e){}
    throw Error(error);
  }
  return res.json();
 },
 async refresh(){
  try{
    const results=await Promise.all(["/api/state","/api/targets","/api/profiles","/api/logs"].map(p=>this.api(p)));
    [this.state.status,this.state.targets,this.state.profiles,this.state.logs]=results;
    UI.all();$("connection").textContent="Соединено";
  }catch(e){this.toast(e.message);$("connection").textContent="Ошибка";}
 },
 async command(cmd,extra={}){
  try{
    this.state.status=await this.api("/api/control",{method:"POST",body:Object.assign({cmd},extra)});
    UI.dashboard();await this.refresh();
  }catch(e){this.toast(e.message);}
 },
 async download(format,id){
  try{
    const path="/api/profiles/export?format="+format+(id?"&id="+encodeURIComponent(id):"");
    let response=await fetch(path,{headers:this.token?{Authorization:"Bearer "+this.token}:{}});
    if(response.status===401){await this.api("/api/state");response=await fetch(path,{headers:{Authorization:"Bearer "+this.token}});}
    if(!response.ok)throw Error("Export HTTP "+response.status);
    const url=URL.createObjectURL(await response.blob());
    const link=document.createElement("a");link.href=url;link.download=(id||"profiles")+"."+format;
    document.body.appendChild(link);link.click();link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),2000);
  }catch(e){this.toast(e.message);}
 },
 openProfile(id){
  this.state.detail=this.state.profiles.find(p=>p.id===id);
  document.querySelector('[data-tab="profiles"]').click();UI.profileDetail();
 },
 connect(){
  const protocol=location.protocol==="https:"?"wss:":"ws:";
  const socket=new WebSocket(protocol+"//"+location.host+"/ws"+(this.token?"?token="+encodeURIComponent(this.token):""));
  socket.onopen=()=>$("connection").textContent="Live";
  socket.onmessage=e=>{
    let p;try{p=JSON.parse(e.data);}catch(_){return;}
    if(p.event==="status"){this.state.status=p.data;UI.dashboard();UI.game();}
    if(p.event==="log"){this.state.logs.push(p.data);this.state.logs=this.state.logs.slice(-5000);UI.logs();}
    if(p.event==="profile")this.api("/api/profiles").then(rows=>{this.state.profiles=rows;UI.profiles();UI.graph();});
    if(p.event==="game_frame"){$("game-frame").src=p.data.image;UI.game();}
    if(p.event==="error")this.toast(p.data.msg);
  };
  socket.onclose=()=>{$("connection").textContent="Offline";setTimeout(()=>this.connect(),3000);};
 }
};
document.addEventListener("DOMContentLoaded",()=>{Handlers.bind();App.refresh().then(()=>App.connect());setInterval(()=>App.refresh(),15000);});
