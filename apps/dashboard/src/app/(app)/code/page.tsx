"use client";
import { FindingsExplorer } from "@/components/FindingsExplorer";
import { PageHeader } from "@/components/ui";

export default function Code() {
  return (<><PageHeader title="Code analysis" subtitle="Deterministic scanner findings across connected repositories. AI explanations are optional and labelled." /><FindingsExplorer /></>);
}
