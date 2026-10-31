"""Generuje sztuczne badania DICOM (bez danych prawdziwych pacjentów) i wysyła je do PACS przez C-STORE.

Użycie: python tools/send_test_studies.py --host 127.0.0.1 --port 4242 --aet PACS
Wymaga: pip install pydicom pynetdicom numpy
"""

import argparse
import datetime

import numpy as np
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import (CTImageStorage, DigitalXRayImageStorageForPresentation, ExplicitVRLittleEndian,
                         MRImageStorage, generate_uid)
from pynetdicom import AE

# Fikcyjni pacjenci - imiona i PESEL-e zmyślone, oznaczone jako TEST.
STUDIES = [
    {"patient": ("TEST^Adam", "TEST0001"), "modality": "CT", "sop": CTImageStorage, "slices": 40,
     "description": "CT glowy bez kontrastu CITO", "priority": "STAT", "referring": "Kowalski^Jan"},
    {"patient": ("TEST^Barbara", "TEST0002"), "modality": "MR", "sop": MRImageStorage, "slices": 24,
     "description": "MR kregoslupa ledzwiowego", "priority": "ROUTINE", "referring": "Wisniewska^Ewa"},
    {"patient": ("TEST^Celina", "TEST0003"), "modality": "DX", "sop": DigitalXRayImageStorageForPresentation,
     "slices": 1, "description": "RTG klatki piersiowej PA", "priority": "ROUTINE", "referring": "Kowalski^Jan"},
]


def phantom(size: int, z: float, modality: str) -> np.ndarray:
    """Prosty fantom: elipsa 'ciała' z kilkoma strukturami, zmieniającymi się między warstwami."""
    y, x = np.mgrid[-1:1:size * 1j, -1:1:size * 1j]
    img = np.full((size, size), -1000.0 if modality == "CT" else 0.0)
    body = (x / 0.85) ** 2 + (y / 0.7) ** 2 < 1
    img[body] = 40 if modality == "CT" else 300
    r = 0.25 * np.sqrt(max(0.0, 1 - (2 * z - 1) ** 2))
    img[(x + 0.35) ** 2 + y ** 2 < r ** 2] = 80 if modality == "CT" else 700
    img[(x - 0.35) ** 2 + (y + 0.1) ** 2 < (r * 0.8) ** 2] = 400 if modality == "CT" else 150
    img[((x / 0.83) ** 2 + (y / 0.68) ** 2 < 1) & ~((x / 0.78) ** 2 + (y / 0.63) ** 2 < 1)] = \
        1000 if modality == "CT" else 900
    img += np.random.default_rng(int(z * 1000)).normal(0, 8, img.shape)
    return img


def build(study: dict, index: int, study_uid: str, series_uid: str) -> Dataset:
    size = 512 if study["modality"] == "CT" else 256 if study["modality"] == "MR" else 1024
    z = index / max(1, study["slices"] - 1)
    pixels = phantom(size, z, study["modality"])
    offset = 1024 if study["modality"] == "CT" else 0
    arr = np.clip(pixels + offset, 0, 4095).astype(np.uint16)

    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = study["sop"]
    ds.SOPInstanceUID = generate_uid()
    ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    ds.SOPClassUID = study["sop"]
    ds.PatientName, ds.PatientID = study["patient"]
    ds.PatientSex, ds.PatientBirthDate = "O", "19700101"
    today = datetime.date.today().strftime("%Y%m%d")
    ds.StudyDate = ds.SeriesDate = today
    ds.StudyTime = datetime.datetime.now().strftime("%H%M%S")
    ds.AccessionNumber = f"TEST{study['patient'][1][-4:]}"
    ds.Modality = study["modality"]
    ds.StudyDescription = study["description"]
    ds.SeriesDescription = study["description"]
    ds.ReferringPhysicianName = study["referring"]
    ds.RequestedProcedurePriority = study["priority"]
    ds.StudyInstanceUID, ds.SeriesInstanceUID = study_uid, series_uid
    ds.StudyID, ds.SeriesNumber, ds.InstanceNumber = "1", 1, index + 1
    ds.ImagePositionPatient = [0, 0, index * 5.0]
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.PixelSpacing = [0.5, 0.5]
    ds.SliceThickness = 5.0
    ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
    ds.Rows, ds.Columns = arr.shape
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 12, 11, 0
    if study["modality"] == "CT":
        ds.RescaleIntercept, ds.RescaleSlope = -1024, 1
        ds.WindowCenter, ds.WindowWidth = 40, 400
    else:
        ds.WindowCenter, ds.WindowWidth = 500, 1000
    ds.PixelData = arr.tobytes()
    return ds


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4242)
    parser.add_argument("--aet", default="PACS")
    args = parser.parse_args()

    ae = AE(ae_title="TESTMODALITY")
    for s in STUDIES:
        ae.add_requested_context(s["sop"], ExplicitVRLittleEndian)
    assoc = ae.associate(args.host, args.port, ae_title=args.aet)
    if not assoc.is_established:
        raise SystemExit("Nie udało się połączyć z PACS")
    for s in STUDIES:
        study_uid, series_uid = generate_uid(), generate_uid()
        for i in range(s["slices"]):
            status = assoc.send_c_store(build(s, i, study_uid, series_uid))
            if not status or status.Status != 0:
                raise SystemExit(f"C-STORE nieudany: {status}")
        print(f"Wysłano {s['modality']} {s['description']} ({s['slices']} obrazów)")
    assoc.release()


if __name__ == "__main__":
    main()
