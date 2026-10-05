import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useDialogFocus } from "./useDialogFocus";
function Dialog({close}:{close:()=>void}) {
  const ref=useDialogFocus<HTMLDivElement>(close);
  return <div ref={ref} tabIndex={-1} role="dialog"><button>First</button><button>Last</button><details><summary>More</summary><button>Hidden control</button></details></div>;
}
afterEach(cleanup);
it("traps keyboard focus, ignores closed disclosure controls, closes with Escape and restores the trigger",()=>{
 const trigger=document.createElement('button');document.body.append(trigger);trigger.focus();
 const close=vi.fn();const {unmount}=render(<Dialog close={close}/>);
 expect(screen.getByRole('dialog')).toHaveFocus();
 fireEvent.keyDown(document,{key:'Tab'});expect(screen.getByRole('button',{name:'First'})).toHaveFocus();
 screen.getByText('More').focus();fireEvent.keyDown(document,{key:'Tab'});expect(screen.getByRole('button',{name:'First'})).toHaveFocus();
 fireEvent.keyDown(document,{key:'Tab',shiftKey:true});expect(screen.getByText('More')).toHaveFocus();
 fireEvent.keyDown(document,{key:'Escape'});expect(close).toHaveBeenCalledOnce();
 unmount();expect(trigger).toHaveFocus();trigger.remove();
});
