import { promises as fs } from "node:fs";
import path from "node:path";
import { NextResponse } from "next/server";

const PROFILE_PHOTOS_DIR = path.join(process.cwd(), "imagenesPerfil");
const VALID_RECORD_ID = /^[a-zA-Z0-9-]+$/;

export const runtime = "nodejs";

export async function POST(request: Request) {
  let formData: FormData;
  try {
    formData = await request.formData();
  } catch {
    // El cuerpo no es un formulario multipart válido: error de la petición.
    return NextResponse.json({ error: "Formulario inválido" }, { status: 400 });
  }

  const recordId = formData.get("recordId");
  const photo = formData.get("photo");

  if (typeof recordId !== "string" || !VALID_RECORD_ID.test(recordId)) {
    return NextResponse.json(
      { error: "recordId inválido" },
      { status: 400 },
    );
  }

  if (!(photo instanceof File) || photo.size === 0) {
    return NextResponse.json({ error: "Archivo inválido" }, { status: 400 });
  }

  const extension = path.extname(photo.name) || ".png";
  const fileName = `${recordId}${extension}`;
  const photoPath = path.join(PROFILE_PHOTOS_DIR, fileName);

  // Primero se guarda la foto nueva: si falla, la anterior sigue intacta.
  try {
    await fs.mkdir(PROFILE_PHOTOS_DIR, { recursive: true });
    const buffer = Buffer.from(await photo.arrayBuffer());
    await fs.writeFile(photoPath, buffer);
  } catch (error) {
    // El mensaje de `fs` incluye rutas del servidor: solo va al log.
    console.error("upload-photo: no se pudo guardar la foto", error);
    return NextResponse.json({ error: "No se pudo guardar la foto" }, { status: 500 });
  }

  // Después se borran las fotos anteriores con otra extensión. Si esto falla, la nueva ya
  // está guardada: se registra y la subida se da por buena.
  try {
    const photoEntries = await fs.readdir(PROFILE_PHOTOS_DIR);
    const previousPhotos = photoEntries.filter(
      (entry) => entry.startsWith(`${recordId}.`) && entry !== fileName,
    );
    await Promise.all(
      previousPhotos.map((entry) => fs.unlink(path.join(PROFILE_PHOTOS_DIR, entry))),
    );
  } catch (error) {
    console.error("upload-photo: no se pudieron borrar las fotos anteriores", error);
  }

  return NextResponse.json({
    path: `/api/profile-photo/${recordId}`,
  });
}
