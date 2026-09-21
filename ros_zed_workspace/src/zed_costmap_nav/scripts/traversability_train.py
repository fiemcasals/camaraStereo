#!/usr/bin/env python3
"""Entrenamiento OFFLINE (Fase 2.3): se corre a mano, APARTE de manejar el
vehiculo -- nunca durante la recoleccion. Lee el dataset que fue guardando
traversability_data_collector.py mientras se manejaba manual, entrena una red
liviana de segmentacion binaria (transitable / no transitable) con
supervision parcial (solo los pixeles que el colector pudo etiquetar solo:
piso cercano = positivo, obstaculo real = negativo; el resto se ignora en la
loss), y exporta el resultado a ONNX para que traversability_infer_node.py lo
use en la Jetson.

No requiere GPU para correr (funciona en CPU, mas lento), pero en la Jetson
conviene con CUDA. No esta pensado para correrse en un loop en vivo: es un
comando que se ejecuta despues de cada sesion de manejo manual, dura minutos,
y el resultado (checkpoint + ONNX) es lo que se usa despues para que el
vehiculo navegue solo.

Uso:
    python3 traversability_train.py --dataset ~/vad_traversability_dataset \
        --epochs 15 --out model.onnx

    # Para seguir entrenando el mismo modelo con una recoleccion nueva
    # (afinado incremental, no entrenar de cero cada vez):
    python3 traversability_train.py --dataset ~/vad_traversability_dataset \
        --epochs 5 --checkpoint-in model.pt --out model.onnx
"""
import argparse
import glob
import os

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader

try:
    import cv2
except ImportError:
    cv2 = None


IMG_SIZE = (256, 256)  # (alto, ancho) que ve la red -- chico para correr rapido en la Jetson


class TinyTraversabilityNet(nn.Module):
    """Segmentacion liviana estilo encoder-decoder chico (en el espiritu de
    Fast-SCNN/BiSeNet: pocas capas, downsample agresivo, upsample al final).
    Pensada para exportar a ONNX -> TensorRT y correr en tiempo real en la
    Jetson, no para maxima precision."""

    def __init__(self):
        super().__init__()
        self.enc1 = nn.Sequential(nn.Conv2d(3, 16, 3, stride=2, padding=1), nn.BatchNorm2d(16), nn.ReLU())
        self.enc2 = nn.Sequential(nn.Conv2d(16, 32, 3, stride=2, padding=1), nn.BatchNorm2d(32), nn.ReLU())
        self.enc3 = nn.Sequential(nn.Conv2d(32, 64, 3, stride=2, padding=1), nn.BatchNorm2d(64), nn.ReLU())
        self.bottleneck = nn.Sequential(nn.Conv2d(64, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU())
        self.dec3 = nn.Sequential(nn.Conv2d(64, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU())
        self.dec2 = nn.Sequential(nn.Conv2d(32, 16, 3, padding=1), nn.BatchNorm2d(16), nn.ReLU())
        self.out_conv = nn.Conv2d(16, 1, 1)  # 1 canal: logit de "transitable"

    def forward(self, x):
        e1 = self.enc1(x)                                            # /2
        e2 = self.enc2(e1)                                            # /4
        e3 = self.enc3(e2)                                            # /8
        b = self.bottleneck(e3)
        d3 = self.dec3(F.interpolate(b, scale_factor=2, mode='bilinear', align_corners=False))   # /4
        d2 = self.dec2(F.interpolate(d3, scale_factor=2, mode='bilinear', align_corners=False))  # /2
        out = self.out_conv(F.interpolate(d2, scale_factor=2, mode='bilinear', align_corners=False))  # /1
        return out  # logits, sigmoid se aplica en la loss / en inferencia


class TraversabilityDataset(Dataset):
    """Cada muestra es una carpeta con rgb.jpg + labels.npy (Nx3: u,v,label
    en la resolucion ORIGINAL de la camara, ver traversability_label.py). Acá
    se reescalan las coordenadas a IMG_SIZE y se arma una mascara densa con
    -100 = ignorar (mayoria), 0 = no transitable, 1 = transitable."""

    def __init__(self, dataset_dir, img_size=IMG_SIZE):
        self.samples = sorted(glob.glob(os.path.join(dataset_dir, "*")))
        self.samples = [s for s in self.samples if os.path.isfile(os.path.join(s, "labels.npy"))]
        if not self.samples:
            raise ValueError(f"no se encontraron muestras en {dataset_dir} -- "
                              f"¿corriste traversability_data_collector.py primero?")
        self.img_size = img_size

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        sample_dir = self.samples[idx]
        rgb = cv2.imread(os.path.join(sample_dir, "rgb.jpg"))
        orig_h, orig_w = rgb.shape[:2]
        rgb = cv2.resize(rgb, (self.img_size[1], self.img_size[0]))
        rgb = cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        img_tensor = torch.from_numpy(rgb).permute(2, 0, 1)  # CHW

        labels = np.load(os.path.join(sample_dir, "labels.npy"))  # Nx3: u,v,label
        mask = np.full(self.img_size, fill_value=-100, dtype=np.int64)  # -100 = ignore_index
        sx = self.img_size[1] / orig_w
        sy = self.img_size[0] / orig_h
        for u, v, label in labels:
            uu = int(u * sx)
            vv = int(v * sy)
            if 0 <= vv < self.img_size[0] and 0 <= uu < self.img_size[1]:
                mask[vv, uu] = 1 if label > 0 else 0
        return img_tensor, torch.from_numpy(mask)


def masked_bce_loss(logits, mask):
    """logits: (B,1,H,W). mask: (B,H,W) con -100=ignorar, 0/1=etiqueta real."""
    valid = mask != -100
    if valid.sum() == 0:
        return None
    target = mask.clone().float()
    target[~valid] = 0.0  # valor dummy, se anula con el peso de abajo
    logits_flat = logits.squeeze(1)
    loss = F.binary_cross_entropy_with_logits(logits_flat, target, reduction='none')
    loss = (loss * valid.float()).sum() / valid.float().sum()
    return loss


def train(dataset_dir, epochs, batch_size, lr, checkpoint_in, checkpoint_out, onnx_out, device):
    ds = TraversabilityDataset(dataset_dir)
    dl = DataLoader(ds, batch_size=batch_size, shuffle=True, num_workers=2, drop_last=False)

    model = TinyTraversabilityNet().to(device)
    if checkpoint_in and os.path.isfile(checkpoint_in):
        model.load_state_dict(torch.load(checkpoint_in, map_location=device))
        print(f"Retomando desde {checkpoint_in}")

    opt = torch.optim.Adam(model.parameters(), lr=lr)

    model.train()
    for epoch in range(epochs):
        total_loss, n_batches = 0.0, 0
        for img, mask in dl:
            img, mask = img.to(device), mask.to(device)
            logits = model(img)
            loss = masked_bce_loss(logits, mask)
            if loss is None:
                continue
            opt.zero_grad()
            loss.backward()
            opt.step()
            total_loss += loss.item()
            n_batches += 1
        avg = total_loss / max(n_batches, 1)
        print(f"epoch {epoch + 1}/{epochs} - loss promedio: {avg:.4f} ({len(ds)} muestras)")

    torch.save(model.state_dict(), checkpoint_out)
    print(f"Checkpoint guardado en {checkpoint_out}")

    model.eval()
    dummy = torch.randn(1, 3, *IMG_SIZE, device=device)
    torch.onnx.export(
        model, dummy, onnx_out,
        input_names=["rgb"], output_names=["traversability_logits"],
        opset_version=12,
    )
    print(f"Exportado a ONNX en {onnx_out}")
    print("Siguiente paso en la Jetson: convertir a TensorRT con "
          f"'trtexec --onnx={onnx_out} --saveEngine=model.trt' para inferencia en tiempo real.")


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset', default=os.path.expanduser('~/vad_traversability_dataset'))
    p.add_argument('--epochs', type=int, default=15)
    p.add_argument('--batch-size', type=int, default=8)
    p.add_argument('--lr', type=float, default=1e-3)
    p.add_argument('--checkpoint-in', default=None, help='para afinar un modelo ya entrenado')
    p.add_argument('--checkpoint-out', default='model.pt')
    p.add_argument('--out', default='model.onnx')
    args = p.parse_args()

    if cv2 is None:
        raise SystemExit("Falta opencv-python (cv2). En la Jetson deberia venir con la imagen de ZED; "
                          "si no, 'pip3 install opencv-python-headless'.")

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f"Entrenando en: {device}")
    train(args.dataset, args.epochs, args.batch_size, args.lr,
          args.checkpoint_in, args.checkpoint_out, args.out, device)
