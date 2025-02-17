import re
import numpy as np
from ScanImageTiffReader import ScanImageTiffReader
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt

tif_path = r'C:\Users\zebrafish\code\2p_visual_stimulation\data'
filename = tif_path + ('\synchro_2_DynamicDots_00002.tif')
n_channels = 2
metadata_all = {}

with ScanImageTiffReader(filename) as tif:
    for trigger in range(n_channels):
        metadata_all[f'auxTrigger{trigger}'] = {}
        for i in range(len(tif)):
            #print(f"Reading frame {idx}...")
            metadata = tif.description(i)  # Full metadata
            aux_trigger_match = re.search(rf"auxTrigger{trigger} = \[(.*?)\]", metadata, re.DOTALL)
            if aux_trigger_match:
                aux_trigger_data = aux_trigger_match.group(1)
                if aux_trigger_data:
                    aux_trigger_values = np.fromstring(aux_trigger_data, sep=',')
                    metadata_all[f'auxTrigger{trigger}'][f'frame{i}'] = aux_trigger_values
                else:
                    pass
            else:
                print(f"aux_trigger_match{trigger} not found in frame {i}")

data_sync = {}
for i, auxTrigger in enumerate(metadata_all.keys()):
    data_sync[auxTrigger] = {}
    frame_numbers = sorted([int(key.replace('frame', '')) for key in metadata_all[auxTrigger].keys()])
    # Identify the start of each consecutive block
    start_frames = []
    for i, frame in enumerate(frame_numbers):
        if i == 0 or frame != frame_numbers[i-1] + 1:
            start_frames.append(frame)
    timestamps = [metadata_all[auxTrigger][f'frame{frame}'][0] for frame in start_frames]
    data_sync[auxTrigger]['start_frames'] = start_frames
    data_sync[auxTrigger]['timestamps'] = timestamps

# Step 3: Compute the difference in timestamps between auxTrigger1 and auxTrigger2
timestamps1 = data_sync['auxTrigger0']['timestamps']
timestamps2 = data_sync['auxTrigger1']['timestamps']

# Align the two lists based on their minimum length
min_length = min(len(timestamps1), len(timestamps2))
timestamps1 = timestamps1[:min_length]
timestamps2 = timestamps2[:min_length]

# Compute differences
time_differences = abs(np.array(timestamps1) - np.array(timestamps2))

# # Step 4: Plot the timestamp differences
plt.figure(figsize=(10, 6))
plt.plot(range(min_length), time_differences, marker='o', linestyle='-', color='b')
plt.title("Timestamp Differences Between auxTrigger1 and auxTrigger2")
plt.xlabel("Index of Start Frame")
plt.ylabel("Timestamp Difference (auxTrigger1 - auxTrigger2)")
plt.ion()
plt.show()