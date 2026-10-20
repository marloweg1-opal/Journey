"""Structural media validation. No semantic inspection or source modification."""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import time

VIDEO = {'.mp4','.mov','.m4v','.avi','.mkv','.wmv','.3gp','.mts','.m2ts'}
PHOTO = {'.jpg','.jpeg','.png','.gif','.webp','.tif','.tiff','.heic','.heif','.dng'}


def stable_hash(path, *, max_bytes=64_000_000, max_seconds=10):
    path = Path(path)
    before = path.stat()
    if before.st_size > max_bytes:
        return {'state':'BUDGET_HELD'}
    digest = hashlib.sha256()
    started = time.monotonic()
    read = 0
    with path.open('rb') as stream:
        while block := stream.read(1024*1024):
            read += len(block)
            if read > max_bytes or time.monotonic()-started > max_seconds:
                return {'state':'BUDGET_HELD'}
            digest.update(block)
    after = path.stat()
    if any(getattr(before,k)!=getattr(after,k) for k in ('st_size','st_mtime_ns','st_ino','st_dev')):
        return {'state':'CHANGED_DURING_READ'}
    return {'state':'HASHED','sha256':digest.hexdigest(),'bytes':read,'mtime_ns':after.st_mtime_ns,'inode':after.st_ino}


def video_proof(probe, decode_codes):
    streams = probe.get('streams', [])
    try:
        duration = float(probe.get('format', {}).get('duration', 0))
    except (ValueError, TypeError):
        duration = 0
    checks = {'container': bool(probe.get('format', {}).get('format_name')),
              'video_stream':any(s.get('codec_type')=='video' and s.get('codec_name') not in (None,'unknown') for s in streams),
              'plausible_duration':math.isfinite(duration) and 0 < duration <= 31*24*3600,
              'sample_decodable':len(decode_codes)==3 and all(isinstance(c,dict) and c.get('exit_code')==0 and c.get('frames',0)>0 for c in decode_codes)}
    return {'state':'SAMPLE_DECODABLE' if all(checks.values()) else 'NEEDS_DIAGNOSIS',
            'usable':False,'checks':checks,'duration_seconds':duration,
            'coverage':'three one-second windows; not full-file recovery proof'}


def validate_video(path, ffprobe, ffmpeg, *, timeout=8):
    options = {'capture_output':True, 'text':True, 'encoding':'utf-8', 'errors':'replace', 'timeout':timeout}
    try:
        probe = subprocess.run([str(ffprobe),'-v','error','-protocol_whitelist','file,pipe','-show_entries',
            'format=format_name,duration:format_tags=creation_time:stream=codec_type,codec_name,width,height',
            '-of','json',str(path)],**options)
        if probe.returncode:
            return {'state':'NEEDS_DIAGNOSIS','usable':False,'reason':'container_probe_failed','error':probe.stderr[:1200]}
        data = json.loads(probe.stdout)
        preliminary = video_proof(data, [])
        codes = []
        if all(preliminary['checks'][key] for key in ('container','video_stream','plausible_duration')):
            duration = preliminary['duration_seconds']
            for position in (0, duration/2, max(0,duration-1)):
                decode = subprocess.run([str(ffmpeg),'-nostdin','-v','error','-xerror','-threads','1',
                    '-protocol_whitelist','file,pipe','-ss',str(position),'-i',str(path),'-t','1',
                    '-map','0:v:0','-map','0:a:0?','-progress','pipe:1','-f','null','-'],**options)
                frames=[int(line.split('=',1)[1]) for line in decode.stdout.splitlines() if line.startswith('frame=') and line.split('=',1)[1].strip().isdigit()]
                codes.append({'exit_code':decode.returncode,'frames':max(frames,default=0)})
        return {**video_proof(data,codes),'structural_metadata':data,'decode_exit_codes':codes}
    except (subprocess.TimeoutExpired, OSError, ValueError) as exc:
        return {'state':'INCONCLUSIVE','usable':False,'reason':type(exc).__name__}


def validate_photo(path, *, pixel_budget=16_000_000):
    try:
        from PIL import Image
        with Image.open(path) as picture:
            width,height = picture.size
            metadata = {'format':picture.format,'width':width,'height':height,'frames':getattr(picture,'n_frames',1)}
            if width*height > pixel_budget:
                return {'state':'BUDGET_HELD','usable':False,'structural_metadata':metadata}
            exif = picture.getexif()
            metadata['provenance_tags'] = {str(k):str(exif[k]) for k in (271,272,306,36867) if k in exif}
            picture.verify()
        with Image.open(path) as picture:
            picture.load()
        return {'state':'DECODED_FIRST_FRAME','usable':False,'structural_metadata':metadata,
                'coverage':'structural integrity and first frame; no semantic inspection'}
    except Exception as exc:
        return {'state':'NEEDS_DIAGNOSIS','usable':False,'reason':type(exc).__name__}


def exact_groups(occurrences):
    groups = {}
    for item in occurrences:
        evidence = item.get('hash', {})
        if evidence.get('state')=='HASHED':
            groups.setdefault((evidence['sha256'],evidence['bytes']),[]).append(item['path'])
    return [{'sha256':key[0],'bytes_per_occurrence':key[1],'occurrences':paths,
             'relationship':'EXACT_BYTE_DUPLICATES','delete_authorized':False}
            for key,paths in groups.items() if len(paths)>1]
