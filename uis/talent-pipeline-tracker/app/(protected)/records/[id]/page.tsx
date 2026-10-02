import { RecordDetailClient } from "./record-detail-client";

type DetailPageProps = {
  params: Promise<{ id: string }>;
};

export default async function RecordDetailPage({ params }: DetailPageProps) {
  const resolvedParams = await params;
  return <RecordDetailClient recordId={resolvedParams.id} />;
}
