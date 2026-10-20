import type { Metadata } from "next";
import { RecordDetailClient } from "./record-detail-client";

export const metadata: Metadata = {
  title: "Candidatura | Talent Pipeline",
};

type DetailPageProps = {
  params: Promise<{ id: string }>;
};

export default async function RecordDetailPage({ params }: DetailPageProps) {
  const resolvedParams = await params;
  return <RecordDetailClient recordId={resolvedParams.id} />;
}
