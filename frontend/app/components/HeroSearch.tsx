"use client";

import { useEffect } from "react";

export default function HeroSearch({className}:{className:string}) {
  const focusSearch=()=>document.getElementById("benchmark-search")?.focus();
  useEffect(()=>{const handler=(event:KeyboardEvent)=>{if(event.key==="/"&&!(["INPUT","SELECT","TEXTAREA"].includes((document.activeElement?.tagName||"")))){event.preventDefault();focusSearch()}};document.addEventListener("keydown",handler);return()=>document.removeEventListener("keydown",handler)},[]);
  return <button className={className} type="button" onClick={focusSearch}><span aria-hidden="true">⌕</span><span>Search hardware, encoder, codec, preset, or result…</span><kbd>/</kbd></button>
}
