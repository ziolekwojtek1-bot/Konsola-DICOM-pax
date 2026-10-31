"""Zestaw pokazowy: sztuczne badania DICOM w różnych modalnościach i formatach zapisu.

Żadne obrazy nie pochodzą od pacjentów - wszystkie są generowane matematycznie (fantomy).
Zestaw sprawdza, czy system poprawnie przyjmuje i wyświetla typowe przypadki z pracowni:

  1. CT głowy CITO z krwiakiem       - 40 warstw, bez kompresji (Explicit VR Little Endian)
  2. CT głowy sprzed 4 miesięcy       - to samo "pacjent", badanie poprzednie do porównania
  3. CT klatki piersiowej             - 30 warstw, JPEG 2000 bezstratny
  4. MR kręgosłupa lędźwiowego        - 20 warstw, JPEG-LS bezstratny
  5. RTG klatki piersiowej (DX)       - 1 obraz 1024x1024, Implicit VR Little Endian
  6. RTG ręki (CR)                    - 1 obraz, kompresja RLE
  7. USG jamy brzusznej               - film 24 klatki, kolor RGB (multiframe)
  8. Mammografia (MG)                 - MONOCHROME1 (odwrócona skala szarości)

Użycie:
  python tools/make_demo_dataset.py --out demo-dicom            # zapis plików .dcm
  python tools/make_demo_dataset.py --send 127.0.0.1:4242       # wysyłka C-STORE jak z aparatu
Wymaga: pip install pydicom pynetdicom numpy pylibjpeg pylibjpeg-openjpeg pyjpegls
"""

import argparse
import datetime
from pathlib import Path

import numpy as np
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import (CTImageStorage, ComputedRadiographyImageStorage, DigitalMammographyXRayImageStorageForPresentation,
                         DigitalXRayImageStorageForPresentation, ExplicitVRLittleEndian, ImplicitVRLittleEndian,
                         JPEG2000Lossless, JPEGLSLossless, MRImageStorage, RLELossless,
                         UltrasoundMultiFrameImageStorage, generate_uid)

rng = np.random.default_rng(2026)
TODAY = datetime.date.today()


def grid(size):
    return np.mgrid[-1:1:size * 1j, -1:1:size * 1j]


def ellipse(y, x, cx, cy, rx, ry):
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 < 1


# ---------- fantomy (wartości w HU dla CT, w jednostkach umownych dla reszty) ----------

def head_ct(z, size=512, bleed=False):
    y, x = grid(size)
    img = np.full((size, size), -1000.0)
    scale = np.sqrt(max(0.05, 1 - (2 * z - 1) ** 2))
    skull = ellipse(y, x, 0, 0, 0.72 * scale + 0.1, 0.88 * scale + 0.1)
    brain = ellipse(y, x, 0, 0, 0.66 * scale + 0.08, 0.82 * scale + 0.08)
    img[skull] = 900
    img[brain] = 35
    img[brain & (np.abs(x) < 0.25 * scale) & ellipse(y, x, 0, -0.05, 0.3, 0.45)] = 30
    # komory boczne
    img[ellipse(y, x, -0.12, -0.05, 0.07 * scale, 0.25 * scale)] = 5
    img[ellipse(y, x, 0.12, -0.05, 0.07 * scale, 0.25 * scale)] = 5
    if bleed and 0.3 < z < 0.75:
        # krwiak podtwardówkowy prawostronny (po lewej stronie obrazu) - sierp pod kością
        crescent = brain & ~ellipse(y, x, 0.06, 0, 0.62 * scale + 0.08, 0.80 * scale + 0.08) & (x < -0.1)
        img[crescent] = 70
    return img + rng.normal(0, 4, img.shape)


def chest_ct(z, size=512):
    y, x = grid(size)
    img = np.full((size, size), -1000.0)
    body = ellipse(y, x, 0, 0.05, 0.9, 0.62)
    img[body] = 40
    img[body & ~ellipse(y, x, 0, 0.05, 0.85, 0.57)] = -80  # tkanka tłuszczowa
    img[ellipse(y, x, -0.42, 0.0, 0.32, 0.42)] = -850  # płuca
    img[ellipse(y, x, 0.42, 0.0, 0.32, 0.42)] = -850
    img[ellipse(y, x, 0.08, 0.1, 0.22, 0.2)] = 45  # serce
    img[ellipse(y, x, 0, 0.5, 0.08, 0.08)] = 700  # kręg
    if 0.4 < z < 0.6:
        img[ellipse(y, x, -0.5, -0.15, 0.04, 0.04)] = 30  # guzek w płucu
    return img + rng.normal(0, 10, img.shape)


def spine_mr(z, size=256):
    y, x = grid(size)
    img = np.zeros((size, size))
    img[ellipse(y, x, 0, 0, 0.9, 0.95)] = 250
    for i in range(5):  # trzony kręgów i krążki (przekrój strzałkowy)
        cy = -0.7 + i * 0.32
        img[(np.abs(x - 0.05) < 0.22) & (np.abs(y - cy) < 0.12)] = 450
        img[(np.abs(x - 0.05) < 0.2) & (np.abs(y - cy - 0.16) < 0.03)] = 800 if i != 3 else 300
    img[(np.abs(x + 0.32) < 0.06 * (1 - abs(z - 0.5)))] = 900  # kanał kręgowy (płyn)
    return np.clip(img + rng.normal(0, 15, img.shape), 0, None)


def chest_xray(size=1024):
    y, x = grid(size)
    img = np.full((size, size), 300.0)
    img[ellipse(y, x, 0, 0.05, 0.85, 0.9)] = 1800
    img[ellipse(y, x, -0.38, -0.05, 0.3, 0.62)] = 700
    img[ellipse(y, x, 0.38, -0.05, 0.3, 0.62)] = 700
    img[ellipse(y, x, 0.12, 0.25, 0.28, 0.25)] = 1700  # serce
    for i in range(9):  # żebra
        img[np.abs(y - (-0.6 + i * 0.13) - 0.15 * x ** 2) < 0.012] += 400
    return np.clip(img + rng.normal(0, 20, img.shape), 0, 4095)


def hand_xray(size=768):
    y, x = grid(size)
    img = np.full((size, size), 200.0)
    img[ellipse(y, x, 0, 0.45, 0.45, 0.4)] = 1500  # dłoń
    for i, cx in enumerate((-0.42, -0.2, 0.0, 0.2, 0.4)):
        length = 0.5 if i else 0.35
        finger = (np.abs(x - cx) < 0.07) & (y < 0.2) & (y > 0.2 - length * 1.6)
        img[finger] = 1500
        img[finger & (np.abs(x - cx) < 0.035)] = 2800  # paliczki
    return np.clip(img + rng.normal(0, 25, img.shape), 0, 4095)


def ultrasound(frame, h=480, w=640):
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot(xx - w / 2, yy + 40)
    angle = np.arctan2(xx - w / 2, yy + 40)
    sector = (r < h + 20) & (np.abs(angle) < 0.6) & (r > 60)
    gray = np.zeros((h, w))
    gray[sector] = rng.rayleigh(45, sector.sum())
    organ = ((xx - w / 2 - 40 * np.sin(frame / 4)) / 140) ** 2 + ((yy - 280) / 90) ** 2 < 1
    gray[organ & sector] *= 0.35  # pęcherzyk/naczynie - hipoechogeniczne
    rgb = np.repeat(np.clip(gray, 0, 255)[..., None], 3, axis=2)
    doppler = organ & sector & (((xx - w / 2) ** 2 + (yy - 280) ** 2) < (40 + 10 * np.sin(frame)) ** 2)
    rgb[doppler] = [200, 30, 30] if frame % 8 < 4 else [30, 60, 220]
    return rgb.astype(np.uint8)


def mammo(h=1200, w=960):
    yy, xx = np.mgrid[0:h, 0:w] / np.array([h, w])[:, None, None]
    img = np.full((h, w), 4000.0)  # MONOCHROME1: duża wartość = czarne tło
    breast = ((xx / 0.75) ** 2 + ((yy - 0.5) / 0.48) ** 2) < 1
    img[breast] = 2200 - 900 * np.exp(-((xx - 0.3) ** 2 + (yy - 0.5) ** 2) / 0.05)[breast]
    img[((xx - 0.42) ** 2 + (yy - 0.38) ** 2) < 0.0006] = 900  # zmiana ogniskowa
    return np.clip(img + rng.normal(0, 30, img.shape), 0, 4095)


# ---------- definicje badań ----------

def days_ago(n):
    return (TODAY - datetime.timedelta(days=n)).strftime("%Y%m%d")


ADAM = ("TEST^Adam", "TEST0001", "19580312", "M")
STUDIES = [
    dict(patient=ADAM, modality="CT", sop=CTImageStorage, ts=ExplicitVRLittleEndian, date=days_ago(0),
         description="CT glowy bez kontrastu CITO", priority="STAT", referring="Kowalski^Jan",
         frames=[lambda z: head_ct(z, bleed=True)] * 40, kind="ct"),
    dict(patient=ADAM, modality="CT", sop=CTImageStorage, ts=ExplicitVRLittleEndian, date=days_ago(120),
         description="CT glowy kontrolne", priority="ROUTINE", referring="Kowalski^Jan",
         frames=[lambda z: head_ct(z)] * 40, kind="ct"),
    dict(patient=("TEST^Barbara", "TEST0002", "19670521", "F"), modality="CT", sop=CTImageStorage,
         ts=JPEG2000Lossless, date=days_ago(0), description="CT klatki piersiowej", priority="ROUTINE",
         referring="Wisniewska^Ewa", frames=[chest_ct] * 30, kind="ct"),
    dict(patient=("TEST^Celina", "TEST0003", "19790101", "F"), modality="MR", sop=MRImageStorage,
         ts=JPEGLSLossless, date=days_ago(0), description="MR kregoslupa ledzwiowego", priority="ROUTINE",
         referring="Wisniewska^Ewa", frames=[spine_mr] * 20, kind="mr"),
    dict(patient=("TEST^Dariusz", "TEST0004", "19850704", "M"), modality="DX",
         sop=DigitalXRayImageStorageForPresentation, ts=ImplicitVRLittleEndian, date=days_ago(0),
         description="RTG klatki piersiowej PA", priority="ROUTINE", referring="Kowalski^Jan",
         frames=[lambda z: chest_xray()], kind="xray"),
    dict(patient=("TEST^Ewa", "TEST0005", "19920215", "F"), modality="CR", sop=ComputedRadiographyImageStorage,
         ts=RLELossless, date=days_ago(0), description="RTG reki lewej PILNE uraz", priority="ROUTINE",
         referring="Kowalski^Jan", frames=[lambda z: hand_xray()], kind="xray"),
    dict(patient=("TEST^Feliks", "TEST0006", "19700909", "M"), modality="US", sop=UltrasoundMultiFrameImageStorage,
         ts=ExplicitVRLittleEndian, date=days_ago(0), description="USG jamy brzusznej", priority="ROUTINE",
         referring="Wisniewska^Ewa", frames=None, kind="us"),
    dict(patient=("TEST^Grazyna", "TEST0007", "19640330", "F"), modality="MG",
         sop=DigitalMammographyXRayImageStorageForPresentation, ts=ExplicitVRLittleEndian, date=days_ago(0),
         description="Mammografia przesiewowa", priority="ROUTINE", referring="Wisniewska^Ewa",
         frames=[lambda z: mammo()], kind="mg"),
]


def base_dataset(study, study_uid, series_uid, index):
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.SOPClassUID = study["sop"]
    ds.SOPInstanceUID = generate_uid()
    ds.file_meta.MediaStorageSOPClassUID = study["sop"]
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.PatientName, ds.PatientID, ds.PatientBirthDate, ds.PatientSex = study["patient"]
    ds.StudyDate = ds.SeriesDate = ds.ContentDate = study["date"]
    ds.StudyTime = ds.SeriesTime = datetime.datetime.now().strftime("%H%M%S")
    ds.AccessionNumber = "DEMO" + study_uid[-6:]
    ds.Modality = study["modality"]
    ds.StudyDescription = ds.SeriesDescription = study["description"]
    ds.ReferringPhysicianName = study["referring"]
    ds.RequestedProcedurePriority = study["priority"]
    ds.InstitutionName = "PRACOWNIA DEMO - DANE FIKCYJNE"
    ds.StudyInstanceUID, ds.SeriesInstanceUID = study_uid, series_uid
    ds.StudyID, ds.SeriesNumber, ds.InstanceNumber = "1", 1, index + 1
    ds.PatientIdentityRemoved = "YES"
    return ds


def set_gray(ds, arr, kind):
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME1" if kind == "mg" else "MONOCHROME2"
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 12, 11, 0
    ds.Rows, ds.Columns = arr.shape
    if kind == "ct":
        ds.RescaleIntercept, ds.RescaleSlope, ds.RescaleType = -1024, 1, "HU"
        arr = arr + 1024
        brain = "glowy" in ds.StudyDescription
        ds.WindowCenter, ds.WindowWidth = (40, 80) if brain else (-600, 1500)
    elif kind == "mr":
        ds.WindowCenter, ds.WindowWidth = 450, 900
    else:
        ds.WindowCenter, ds.WindowWidth = 2048, 4096
    return np.clip(arr, 0, 4095).astype(np.uint16)


def build_series(study):
    study_uid, series_uid = generate_uid(), generate_uid()
    if study["kind"] == "us":
        ds = base_dataset(study, study_uid, series_uid, 0)
        frames = np.stack([ultrasound(f) for f in range(24)])
        ds.SamplesPerPixel, ds.PhotometricInterpretation, ds.PlanarConfiguration = 3, "RGB", 0
        ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 8, 8, 7, 0
        ds.NumberOfFrames, (ds.Rows, ds.Columns) = len(frames), frames.shape[1:3]
        ds.FrameTime, ds.CineRate = 66.7, 15
        ds.FrameIncrementPointer = 0x00181063
        ds.file_meta.TransferSyntaxUID = study["ts"]
        ds.PixelData = frames.tobytes()
        yield ds
        return

    count = len(study["frames"])
    for i, make in enumerate(study["frames"]):
        ds = base_dataset(study, study_uid, series_uid, i)
        arr = set_gray(ds, make(i / max(1, count - 1)), study["kind"])
        if study["kind"] in ("ct", "mr"):
            ds.ImagePositionPatient = [0, 0, i * 5.0]
            ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
            ds.SliceThickness, ds.SliceLocation = 5.0, i * 5.0
            ds.PixelSpacing = [0.5, 0.5] if study["kind"] == "ct" else [1.0, 1.0]
        else:
            ds.PixelSpacing = ds.ImagerPixelSpacing = [0.15, 0.15]
            ds.ViewPosition = "CC" if study["kind"] == "mg" else "PA"
        if study["ts"] in (JPEG2000Lossless, JPEGLSLossless, RLELossless):
            ds.compress(study["ts"], arr)
        else:
            ds.file_meta.TransferSyntaxUID = study["ts"]
            ds.PixelData = arr.tobytes()
        yield ds


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="katalog na pliki .dcm")
    parser.add_argument("--send", help="host:port odbiorcy DICOM, np. 127.0.0.1:4242")
    parser.add_argument("--aet", default="PACS")
    args = parser.parse_args()
    if not args.out and not args.send:
        parser.error("podaj --out albo --send")

    assoc = None
    if args.send:
        from pynetdicom import AE
        ae = AE(ae_title="DEMOMODALITY")
        for s in STUDIES:
            ae.add_requested_context(s["sop"], s["ts"])
        host, port = args.send.split(":")
        assoc = ae.associate(host, int(port), ae_title=args.aet)
        if not assoc.is_established:
            raise SystemExit("Nie udało się połączyć z PACS")

    for n, study in enumerate(STUDIES, 1):
        count = 0
        for ds in build_series(study):
            if args.out:
                folder = Path(args.out) / f"{n:02d}_{study['modality']}_{study['description'].replace(' ', '_')}"
                folder.mkdir(parents=True, exist_ok=True)
                ds.save_as(folder / f"{ds.InstanceNumber:03d}.dcm", enforce_file_format=True)
            if assoc:
                status = assoc.send_c_store(ds)
                if not status or status.Status != 0:
                    raise SystemExit(f"C-STORE nieudany: {status}")
            count += 1
        print(f"{n}. {study['modality']:3} {study['description']:32} {count:3} obr.  {study['ts'].name}")
    if assoc:
        assoc.release()


if __name__ == "__main__":
    main()
