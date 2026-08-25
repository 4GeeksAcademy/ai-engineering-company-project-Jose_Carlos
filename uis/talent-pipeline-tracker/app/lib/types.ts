export const STATUS_VALUES = [
  "received",
  "in_progress",
  "selected",
  "discarded",
] as const;

export const STAGE_VALUES = [
  "pending",
  "review",
  "personal_interview",
  "technical_interview",
  "offer_presented",
] as const;

export type RecordStatus = (typeof STATUS_VALUES)[number];
export type RecordStage = (typeof STAGE_VALUES)[number];

export type CandidateRecord = {
  id: string;
  full_name: string;
  email: string;
  phone: string;
  position: string;
  linkedin_url: string | null;
  cv_url: string | null;
  status: RecordStatus;
  stage: RecordStage;
  experience_years: number;
  notes_count: number;
  applied_at: string;
  updated_at: string;
};

export type RecordCreatePayload = {
  full_name: string;
  email: string;
  phone: string;
  position: string;
  experience_years: number;
  linkedin_url?: string | null;
  cv_url?: string | null;
  status?: RecordStatus;
  stage?: RecordStage;
};

export type RecordReplacePayload = {
  full_name: string;
  email: string;
  phone: string;
  position: string;
  experience_years: number;
  linkedin_url?: string | null;
  cv_url?: string | null;
  status: RecordStatus;
  stage: RecordStage;
};

export type Note = {
  id: string;
  record_id: string;
  content: string;
  created_at: string;
};

export type RecordsResponse = {
  total: number;
  page: number;
  limit: number;
  data: CandidateRecord[];
};

export type NotesResponse = {
  data: Note[];
  meta: {
    total: number;
  };
};
