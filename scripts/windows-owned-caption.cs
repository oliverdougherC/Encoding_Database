using System;
using System.Text;
using System.Runtime.InteropServices;

// Operator-only normal caption activation. No keys, buttons or policy bypasses.
public static class EdbOwnedCaption {
 [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left,Top,Right,Bottom; }
 [StructLayout(LayoutKind.Sequential)] public struct Point { public int X,Y; }
 [StructLayout(LayoutKind.Sequential)] struct TitleInfo { public uint size; public Rect bounds; [MarshalAs(UnmanagedType.ByValArray,SizeConst=6)] public uint[] states; }
 [StructLayout(LayoutKind.Sequential)] struct MouseData { public int x,y; public uint data,flags,time; public UIntPtr extra; }
 [StructLayout(LayoutKind.Sequential)] struct Input { public uint type; public MouseData mouse; }
 public sealed class Receipt { public string Error,Desktop; public long Root; public uint Owner,InsertedCount,ReleaseCount; public int InputSize,Win32Error; public Rect Window,TitleBar; public Point Point,CursorBefore,CursorAfter; public bool Visible,Enabled,Minimized,ExactPointRoot,PointOwnerMatches,CaptionHit,ForegroundAfter; }
 [DllImport("user32.dll")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
 [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h,out uint owner);
 [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h,out Rect r);
 [DllImport("user32.dll")] static extern bool GetTitleBarInfo(IntPtr h,ref TitleInfo info);
 [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] static extern bool IsWindowEnabled(IntPtr h);
 [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
 [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] static extern IntPtr WindowFromPoint(Point point);
 [DllImport("user32.dll")] static extern IntPtr GetAncestor(IntPtr h,uint flags);
 [DllImport("user32.dll")] static extern IntPtr MonitorFromPoint(Point point,uint flags);
 [DllImport("user32.dll")] static extern bool GetCursorPos(out Point point);
 [DllImport("user32.dll")] static extern int GetSystemMetrics(int index);
 [DllImport("user32.dll")] static extern short GetAsyncKeyState(int key);
 [DllImport("user32.dll",SetLastError=true)] static extern IntPtr OpenInputDesktop(uint flags,bool inherit,uint access);
 [DllImport("user32.dll")] static extern bool CloseDesktop(IntPtr h);
 [DllImport("user32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool GetUserObjectInformation(IntPtr h,int index,StringBuilder value,int bytes,out int required);
 [DllImport("user32.dll",SetLastError=true)] static extern IntPtr SendMessageTimeout(IntPtr h,uint m,IntPtr w,IntPtr l,uint flags,uint timeout,out UIntPtr result);
 [DllImport("user32.dll",SetLastError=true)] static extern uint SendInput(uint count,Input[] input,int size);
 static bool HeldInput() {foreach(int key in new int[]{1,2,4,5,6,16,17,18,91,92})if((GetAsyncKeyState(key)&0x8000)!=0)return true;return false;}
 static bool Match(IntPtr root,uint owner,Point point,out bool caption) {
  caption=false;uint actual,atPointOwner;IntPtr atPoint=WindowFromPoint(point);
  if(GetWindowThreadProcessId(root,out actual)==0 || actual!=owner || atPoint!=root || GetAncestor(atPoint,2)!=root || GetWindowThreadProcessId(atPoint,out atPointOwner)==0 || atPointOwner!=owner || !IsWindowVisible(root) || !IsWindowEnabled(root) || IsIconic(root) || MonitorFromPoint(point,0)==IntPtr.Zero)return false;
  UIntPtr hit;long packed=((long)point.X&65535)|(((long)point.Y&65535)<<16);
  caption=SendMessageTimeout(root,0x0084,IntPtr.Zero,new IntPtr(packed),2,1000,out hit)!=IntPtr.Zero && hit.ToUInt64()==2;
  return caption;
 }
 public static Receipt ClickOnce(IntPtr root,uint owner) {
  var r=new Receipt();r.Root=root.ToInt64();r.Owner=owner;r.InputSize=Marshal.SizeOf(typeof(Input));
  IntPtr oldDpi=SetThreadDpiAwarenessContext(new IntPtr(-4));
  if(oldDpi==IntPtr.Zero){r.Error="Cannot establish physical caption coordinates.";return r;}
  try {
   IntPtr desktop=OpenInputDesktop(0,false,1);if(desktop==IntPtr.Zero){r.Error="Input desktop is unavailable; no input.";r.Win32Error=Marshal.GetLastWin32Error();return r;}
   try {var name=new StringBuilder(256);int needed;if(GetUserObjectInformation(desktop,2,name,512,out needed))r.Desktop=name.ToString();} finally {CloseDesktop(desktop);}
   if(r.Desktop!="Default" || HeldInput()){r.Error="Secure desktop or held mouse/modifier input; no click.";return r;}
   if(!GetCursorPos(out r.CursorBefore)||!GetWindowRect(root,out r.Window)){r.Error="Cannot observe caption/cursor geometry.";return r;}
   var title=new TitleInfo();title.size=(uint)Marshal.SizeOf(typeof(TitleInfo));title.states=new uint[6];
   if(!GetTitleBarInfo(root,ref title)){r.Error="Cannot observe native title bar.";return r;}
   r.TitleBar=title.bounds;r.Point.X=(title.bounds.Left+title.bounds.Right)/2;r.Point.Y=(title.bounds.Top+title.bounds.Bottom)/2;
   if(r.Point.X < -32768 || r.Point.X > 32767 || r.Point.Y < -32768 || r.Point.Y > 32767){r.Error="Caption point exceeds hit-test coordinate range.";return r;}
   r.Visible=IsWindowVisible(root);r.Enabled=IsWindowEnabled(root);r.Minimized=IsIconic(root);
   uint atOwner;IntPtr at=WindowFromPoint(r.Point);GetWindowThreadProcessId(at,out atOwner);r.ExactPointRoot=at==root && GetAncestor(at,2)==root;r.PointOwnerMatches=atOwner==owner;
   bool caption;if(!Match(root,owner,r.Point,out caption)){r.Error="Caption point is not an unoccluded exact owned HTCAPTION target.";return r;}r.CaptionHit=caption;
   int left=GetSystemMetrics(76),top=GetSystemMetrics(77),width=GetSystemMetrics(78),height=GetSystemMetrics(79);
   if(width<=1||height<=1||r.Point.X<left||r.Point.X>=left+width||r.Point.Y<top||r.Point.Y>=top+height){r.Error="Caption point is outside the physical virtual desktop.";return r;}
   Point current;if(!GetCursorPos(out current)||current.X!=r.CursorBefore.X||current.Y!=r.CursorBefore.Y||HeldInput()||!Match(root,owner,r.Point,out caption)){r.Error="Input/window changed during validation; no click.";return r;}
   var move=new Input();move.mouse.x=(int)Math.Round((r.Point.X-left)*65535.0/(width-1));move.mouse.y=(int)Math.Round((r.Point.Y-top)*65535.0/(height-1));move.mouse.flags=0xC001;
   var down=new Input();down.mouse.flags=2;var up=new Input();up.mouse.flags=4;
   r.InsertedCount=SendInput(3,new Input[]{move,down,up},r.InputSize);r.Win32Error=Marshal.GetLastWin32Error();
   if(r.InsertedCount!=3){if(r.InsertedCount>=2)r.ReleaseCount=SendInput(1,new Input[]{up},r.InputSize);r.Error="Native caption input was not inserted completely.";}
   GetCursorPos(out r.CursorAfter);r.ForegroundAfter=GetForegroundWindow()==root;
   // Leave the pointer at its resulting position; never restore over user movement.
   return r;
  } finally {SetThreadDpiAwarenessContext(oldDpi);}
 }
}
