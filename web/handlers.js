/* Form actions and task controls. */
const Handlers={
 async importText(text){
  const lines=text.split(/\r?\n/).map(x=>x.trim()).filter(x=>x&&!x.startsWith("#"));
  try{
   const result=await App.api("/api/targets/import",{method:"POST",body:{lines}});
   App.toast("Импортировано: "+result.count);await App.refresh();
  }catch(e){App.toast(e.message);}
 },
 bind(){
  document.querySelectorAll("nav [data-tab]").forEach(button=>button.onclick=()=>{
   document.querySelectorAll("nav [data-tab]").forEach(x=>x.classList.toggle("active",x===button));
   document.querySelectorAll("section.panel").forEach(x=>x.classList.toggle("active",x.id===button.dataset.tab));
   if(button.dataset.tab==="graph")UI.graph();
   if(button.dataset.tab==="settings")UI.loadSettings();
  });
  [["start-osint","start","osint"],["pause","pause"],["resume","resume"],["stop","stop"],
   ["game-start","start","game"],["game-pause","pause"],["game-resume","resume"],["game-stop","stop"]
  ].forEach(([id,cmd,mode])=>$(id).onclick=()=>App.command(cmd,mode?{mode}:{}));
  $("add-target").onsubmit=async event=>{
   event.preventDefault();
   try{
    await App.api("/api/targets",{method:"POST",body:{value:$("target-value").value}});
    $("target-value").value="";await App.refresh();
   }catch(e){App.toast(e.message);}
  };
  $("target-file").onchange=async event=>{
   const file=event.target.files[0];if(file)await this.importText(await file.text());
   event.target.value="";
  };
  const zone=$("dropzone");
  zone.ondragover=e=>{e.preventDefault();zone.classList.add("drag");};
  zone.ondragleave=()=>zone.classList.remove("drag");
  zone.ondrop=async e=>{
   e.preventDefault();zone.classList.remove("drag");
   const file=e.dataTransfer.files[0];if(file)await this.importText(await file.text());
  };
  $("select-all").onchange=event=>{
   App.state.selected=new Set(event.target.checked?App.state.targets.map(x=>x.id):[]);
   UI.targets();
  };
  $("target-rows").onchange=e=>{
   if(!e.target.matches("[data-select]"))return;
   if(e.target.checked)App.state.selected.add(e.target.dataset.select);
   else App.state.selected.delete(e.target.dataset.select);
  };
  $("target-rows").onclick=async event=>{
   const button=event.target.closest("button[data-action]");
   if(!button)return;
   const id=button.dataset.id;
   try{
    if(button.dataset.action==="run")await App.command("start",{mode:"osint",target_id:id});
    if(button.dataset.action==="delete"){
     await App.api("/api/targets/"+encodeURIComponent(id),{method:"DELETE"});await App.refresh();
    }
    if(button.dataset.action==="edit"){
     const target=App.state.targets.find(x=>x.id===id);
     const value=prompt("Изменить источник",target.value);
     if(value!==null){await App.api("/api/targets/"+encodeURIComponent(id),{
      method:"PATCH",body:{value}});await App.refresh();}
    }
   }catch(e){App.toast(e.message);}
  };
  $("delete-selected").onclick=async()=>{
   if(!App.state.selected.size||!confirm("Удалить выбранные цели?"))return;
   try{
    await App.api("/api/targets/bulk",{method:"POST",body:{ids:[...App.state.selected]}});
    App.state.selected.clear();await App.refresh();
   }catch(e){App.toast(e.message);}
  };
  $("run-selected").onclick=()=>{
   const id=[...App.state.selected][0];
   if(id)App.command("start",{mode:"osint",target_id:id});
   else App.toast("Выберите цель");
  };
  $("profile-search").oninput=()=>UI.profiles();
  $("profile-filter").onchange=()=>UI.profiles();
  $("profile-grid").onclick=e=>{
   const button=e.target.closest("button[data-id]");if(button)App.openProfile(button.dataset.id);
  };
  $("close-detail").onclick=()=>{$("profile-detail").hidden=true;App.state.detail=null;};
  $("export-json").onclick=()=>App.download("json");
  $("export-csv").onclick=()=>App.download("csv");
  $("single-json").onclick=()=>App.state.detail&&App.download("json",App.state.detail.id);
  $("single-csv").onclick=()=>App.state.detail&&App.download("csv",App.state.detail.id);
  $("log-level").onchange=()=>UI.logs();
  $("log-search").oninput=()=>UI.logs();
  $("download-logs").onclick=()=>{
   const content=App.state.logs.map(x=>[x.ts,x.level,x.msg].join(" ")).join("\n");
   const url=URL.createObjectURL(new Blob([content],{type:"text/plain"}));
   const a=document.createElement("a");a.href=url;a.download="agent.log";a.click();
   setTimeout(()=>URL.revokeObjectURL(url),2000);
  };
  $("settings-form").onsubmit=async event=>{
   event.preventDefault();
   const env={},prompts={};
   document.querySelectorAll("[data-env]").forEach(input=>env[input.dataset.env]=input.value);
   document.querySelectorAll("[data-prompt]").forEach(input=>prompts[input.dataset.prompt]=input.value);
   try{
    await App.api("/api/config",{method:"POST",body:{env,prompts}});
    App.toast("Настройки обновлены");await UI.loadSettings();
   }catch(e){App.toast(e.message);}
  };
 }
};
