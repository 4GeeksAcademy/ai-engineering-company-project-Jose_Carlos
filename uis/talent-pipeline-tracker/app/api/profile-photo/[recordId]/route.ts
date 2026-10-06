import { promises as fs } from "node:fs";
import path from "node:path";
import { NextResponse } from "next/server";

const PROFILE_PHOTOS_DIR = path.join(process.cwd(), "imagenesPerfil");
const DEFAULT_PHOTO_PATH = path.join(PROFILE_PHOTOS_DIR, "imagenPerfil.png");
const VALID_RECORD_ID = /^[a-zA-Z0-9-]+$/;

type RouteContext = {
  params: Promise<{ recordId: string }>;
};

export const runtime = "nodejs";

function getContentType(filePath: string): string {
  const extension = path.extname(filePath).toLowerCase();
  if (extension === ".jpg" || extension === ".jpeg") return "image/jpeg";
  if (extension === ".webp") return "image/webp";
  if (extension === ".gif") return "image/gif";
  if (extension === ".svg") return "image/svg+xml";
  return "image/png";
}

export async function GET(_: Request, context: RouteContext) {
  const { recordId } = await context.params;

  if (!VALID_RECORD_ID.test(recordId)) {
    return NextResponse.json({ error: "recordId inválido" }, { status: 400 });
  }

  let targetPhotoPath = DEFAULT_PHOTO_PATH;

  try {
    const files = await fs.readdir(PROFILE_PHOTOS_DIR);
    const matchedPhoto = files.find((fileName) => fileName.startsWith(`${recordId}.`));
    if (matchedPhoto) {
      targetPhotoPath = path.join(PROFILE_PHOTOS_DIR, matchedPhoto);
    }
  } catch (error) {
    const isMissingDir =
      typeof error === "object" &&
      error !== null &&
      "code" in error &&
      error.code === "ENOENT";
    if (!isMissingDir) {
      // El mensaje de `fs` incluye la ruta absoluta del servidor: solo va al log.
      console.error("profile-photo: no se pudo leer el directorio de fotos", error);
      return photoError();
    }
  }

  try {
    return await servePhoto(targetPhotoPath);
  } catch (error) {
    if (targetPhotoPath === DEFAULT_PHOTO_PATH) {
      console.error("profile-photo: no se pudo leer la foto por defecto", error);
      return photoError();
    }
  }

  // La foto del registro no se pudo leer: se sirve la foto por defecto.
  try {
    return await servePhoto(DEFAULT_PHOTO_PATH);
  } catch (error) {
    console.error("profile-photo: no se pudo leer la foto por defecto", error);
    return photoError();
  }
}

async function servePhoto(photoPath: string) {
  const fileBuffer = await fs.readFile(photoPath);
  return new NextResponse(fileBuffer, {
    headers: {
      "Content-Type": getContentType(photoPath),
      "Cache-Control": "no-store",
    },
  });
}

function photoError() {
  return NextResponse.json({ error: "No se pudo cargar la foto" }, { status: 500 });
}
