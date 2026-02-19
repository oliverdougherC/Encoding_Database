"use client";

import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, ScatterChart, RadarChart, HeatmapChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  VisualMapComponent,
  RadarComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
// Register all components once at module load
echarts.use([
  BarChart,
  LineChart,
  ScatterChart,
  RadarChart,
  HeatmapChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  VisualMapComponent,
  RadarComponent,
  CanvasRenderer,
]);

// Use a permissive type — ECharts validates the shape at runtime
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type EChartsOption = Record<string, any>;

interface Props {
  option: EChartsOption;
  height?: number | string;
  style?: React.CSSProperties;
}

export default function EChart({ option, height = "100%", style }: Props) {
  const divRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null);

  useEffect(() => {
    const el = divRef.current;
    if (!el) return;
    const chart = echarts.init(el, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, { replaceMerge: ["series"] });
  }, [option]);

  return <div ref={divRef} style={{ width: "100%", height, ...style }} />;
}
