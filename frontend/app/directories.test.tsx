import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import HardwarePage from "./hardware/page";
import EncodersPage from "./encoders/page";
import { fetchHardwareDirectory, fetchEncoderDirectory } from "./lib/api";
vi.mock("./lib/api", () => ({
  fetchHardwareDirectory: vi.fn(async () => ({kind:"hardware",truncated:false,items:[{id:"cpu-gpu",cpuModel:"Apple M2",gpuModel:null,encoderCount:1,codecFamilies:["hevc"],acceptedCount:0,suspectCount:4,configurationCount:2,browseFilters:{cpu:"Apple M2"}}]})),
  fetchEncoderDirectory: vi.fn(async () => ({kind:"encoders",truncated:false,items:[{id:"encoder",encoderName:"hevc_videotoolbox",codecFamily:"hevc",acceptedCount:3,suspectCount:1,configurationCount:2,browseFilters:{search:"hevc_videotoolbox"}}]})),
}));
afterEach(() => { cleanup();vi.clearAllMocks(); });
describe("observational coverage directories", () => {
 it("includes suspect-only hardware without presenting it as accepted or scored", async () => {
  render(await HardwarePage({}));
  expect(screen.getByRole("heading", {name:"Apple M2"})).toBeInTheDocument();
  expect(screen.getByRole("link", {name:/Browse.*Apple M2/})).toHaveAttribute("href","/?cpu=Apple+M2");
  expect(document.body).toHaveTextContent("0 accepted");expect(document.body).toHaveTextContent("4 suspect");
  expect(document.body).not.toHaveTextContent(/Mean FPS|Mean VMAF|PL Score|Verified runs/);
 });
 it.each([
  ["Apple M4 Pro", "GPU / accelerator"],
  ["not-applicable", "GPU not applicable"],
  [null, "GPU not reported"],
 ] as const)("distinguishes GPU attribution %s without claiming CPU-only encoding",async (gpuModel,description)=>{
  vi.mocked(fetchHardwareDirectory).mockResolvedValueOnce({kind:"hardware",truncated:false,items:[{id:"m4",cpuModel:"Apple M4 Pro",gpuModel,encoderCount:1,codecFamilies:["hevc"],acceptedCount:1,suspectCount:0,configurationCount:1,browseFilters:{cpu:"Apple M4 Pro"}}]});
  render(await HardwarePage({}));
  expect(screen.getByText(description)).toBeInTheDocument();
  expect(screen.getAllByText("Apple M4 Pro")).toHaveLength(1);
  expect(document.body).not.toHaveTextContent(/CPU-only|software encoding/);
 });
 it("links encoder coverage to raw evidence rather than average unrelated workloads", async () => {
  render(await EncodersPage({}));
  expect(screen.getByRole("link", {name:/Browse.*hevc_videotoolbox/})).toHaveAttribute("href","/?search=hevc_videotoolbox");
  expect(document.body).toHaveTextContent("3 accepted");expect(document.body).toHaveTextContent("1 suspect");
  expect(document.body).not.toHaveTextContent(/Mean FPS|Mean VMAF/);
 });
 it.each(["hardware","encoders"])("discloses a capped %s directory",async kind=>{
  if(kind==='hardware')vi.mocked(fetchHardwareDirectory).mockResolvedValueOnce({kind,items:[],truncated:true});
  else vi.mocked(fetchEncoderDirectory).mockResolvedValueOnce({kind:"encoders",items:[],truncated:true});
  render(await (kind==='hardware'?HardwarePage({}):EncodersPage({})));
  expect(screen.getByText(/Showing a limited directory/)).toBeInTheDocument();
  expect(screen.getByRole('link',{name:'Browse all results'})).toHaveAttribute('href','/');
 });
});
