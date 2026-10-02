"use client";

import { useEffect, useRef, useState } from "react";
import { API_URL, api, getToken } from "@/lib/api";

export type RealtimeEvent={
  id:number;
  topic:string;
  audience:string;
  tenant_id?:number|null;
  user_id?:number|null;
  entity_type?:string|null;
  entity_id?:string|null;
  payload:Record<string,unknown>;
  created_at?:string|null;
};

const LAST_EVENT_KEY="meloli_realtime_last_event_id";

function wsBase(){
  try{
    const url=new URL(API_URL);
    url.protocol=url.protocol==="https:"?"wss:":"ws:";
    return url.toString().replace(/\/$/,"");
  }catch{
    return API_URL.replace(/^http/,"ws").replace(/\/$/,"");
  }
}

export default function RealtimeBridge(){
  const [sessionVersion,setSessionVersion]=useState(0);
  const socketRef=useRef<WebSocket|null>(null);
  const retryRef=useRef<number|undefined>(undefined);
  const attemptRef=useRef(0);

  useEffect(()=>{
    const changed=()=>setSessionVersion(v=>v+1);
    window.addEventListener("meloli:session",changed);
    window.addEventListener("storage",changed);
    return()=>{window.removeEventListener("meloli:session",changed);window.removeEventListener("storage",changed)};
  },[]);

  useEffect(()=>{
    let stopped=false;

    async function connect(){
      const token=getToken();
      if(!token||stopped)return;
      try{
        const {ticket}=await api<{ticket:string;expires_in:number}>("/api/v1/realtime/ticket",{method:"POST"},true);
        if(stopped)return;
        const after=sessionStorage.getItem(LAST_EVENT_KEY)||"0";
        const socket=new WebSocket(wsBase()+"/api/v1/realtime/ws?ticket="+encodeURIComponent(ticket)+"&after="+encodeURIComponent(after));
        socketRef.current=socket;

        socket.onopen=()=>{attemptRef.current=0;window.dispatchEvent(new CustomEvent("meloli:realtime-status",{detail:{connected:true}}));};
        socket.onmessage=(message)=>{
          try{
            const data=JSON.parse(message.data);
            if(data.type!=="event")return;
            sessionStorage.setItem(LAST_EVENT_KEY,String(data.id));
            window.dispatchEvent(new CustomEvent<RealtimeEvent>("meloli:realtime",{detail:data}));
          }catch{}
        };
        socket.onclose=()=>{
          if(stopped)return;
          window.dispatchEvent(new CustomEvent("meloli:realtime-status",{detail:{connected:false}}));
          const delay=Math.min(30000,1000*Math.pow(2,Math.min(5,attemptRef.current++)));
          retryRef.current=window.setTimeout(connect,delay);
        };
        socket.onerror=()=>socket.close();
      }catch{
        if(stopped)return;
        const delay=Math.min(30000,1000*Math.pow(2,Math.min(5,attemptRef.current++)));
        retryRef.current=window.setTimeout(connect,delay);
      }
    }

    connect();
    return()=>{
      stopped=true;
      if(retryRef.current)window.clearTimeout(retryRef.current);
      socketRef.current?.close();
      socketRef.current=null;
    };
  },[sessionVersion]);

  return null;
}

export function subscribeRealtime(handler:(event:RealtimeEvent)=>void,topics?:string[]){
  const listener=(raw:Event)=>{
    const event=(raw as CustomEvent<RealtimeEvent>).detail;
    if(!event)return;
    if(topics&&topics.length&&!topics.some(topic=>event.topic===topic||event.topic.startsWith(topic+".")))return;
    handler(event);
  };
  window.addEventListener("meloli:realtime",listener);
  return()=>window.removeEventListener("meloli:realtime",listener);
}
