import json
import boto3
import os
import yaml
import requests
import shutil
from jinja2 import Template

# Initialise Configuration Variables
ACCESS_KEY = os.environ.get('ACCESS_KEY')
SECRET_KEY = os.environ.get('SECRET_KEY')
AWS_REGION = os.environ.get('AWS_REGION')
OSS_IP = os.environ.get('OSS_IP')
TARGET_BUCKET = os.environ.get('TARGET_BUCKET')
FFMPEG_TRANSCODING_PROFILES = os.environ.get('FFMPEG_TRANSCODING_PROFILES')
USP_LICENSE_KEY = os.environ.get('USP_LICENSE_KEY')

# Set Credentials for Objects
boto3.setup_default_session(
    aws_access_key_id=ACCESS_KEY,
    aws_secret_access_key=SECRET_KEY,
    region_name=AWS_REGION
)

# Scripts for encoding/transcoding input video file
pass1 = Template('ffmpeg -y -i {{ input_file }} -an -c:v libx264 -preset:v {{ preset }} -threads 0 -r {{ fps }} -g {{ gop }} -keyint_min {{ gop }} -sc_threshold 0 -x264opts bframes=1 -pass 1 -b:v {{ bitrate }} -profile:v {{ profile }} -s {{ size }} -f mp4 -strict experimental -movflags frag_keyframe+empty_moov {{ output_file }}')
pass2 = Template('ffmpeg -y -i {{ input_file }} -c:a aac -ac 2 -ab {{ audio_bitrate }} -c:v libx264 -preset:v {{ preset }} -threads 0 -r {{ fps }} -g {{ gop }} -keyint_min {{ gop }} -sc_threshold 0 -x264opts bframes=1 -pass 2 -b:v {{ bitrate }} -profile:v {{ profile }} -s {{ size }} -f mp4 -strict experimental -movflags frag_keyframe+empty_moov {{ output_file }}')

def handler(context, event):
    context.logger.info('Using Objects event to encode/transcode file')
    resp = json.loads(event.body)

    # Get bucket name and filename from Objects PUT event    
    bucket = resp['Records'][0]['s3']['bucket']['name']
    input_filename = resp['Records'][0]['s3']['object']['key']

    filename = input_filename.split('.')[0].lower()

    # Create temp workspace for downloading and converting video file
    work_path = '/tmp/{}'.format(filename)
    rendered_path = work_path + '/output'

    os.makedirs(rendered_path)

    temp_filename = work_path + '/' + input_filename.lower()

    # Download the video file
    client = boto3.client('s3',endpoint_url=OSS_IP)
    client.download_file(Bucket=bucket,
                        Key=input_filename,
                        Filename=temp_filename)

    # Get the table from external source (GitHub) with profiles for output videos
    profiles = requests.get(FFMPEG_TRANSCODING_PROFILES)
    qualities = yaml.load(profiles.content, Loader=yaml.FullLoader)['qualities']

    for q in qualities:

        output_filename = filename + '_' + q + '.mp4'
        output_path_filename = rendered_path + '/' + output_filename

        qualities[q]['input_file'] = temp_filename
        qualities[q]['output_file'] = output_path_filename

        command = pass1.render(qualities[q])
        os.system(command)

        command = pass2.render(qualities[q])
        os.system(command)

        response = client.upload_file(Bucket=TARGET_BUCKET,
                                    Key=filename + '/' + output_filename,
                                    Filename=output_path_filename)

    # Create manifest file with Origin mp4split for VOD
    license_path = work_path + '/license'
    ism_filename = '{}.ism'.format(filename)
    ism_path_filename = rendered_path + '/' + ism_filename

    with open(license_path, 'w') as f:
        f.write(USP_LICENSE_KEY)

    os.system('cd {} && mp4split --license-key={} -o {} *'.format(
        rendered_path,
        license_path,
        ism_filename
    ))

    response = client.upload_file(Bucket=TARGET_BUCKET,
                                Key=filename + '/' + ism_filename,
                                Filename=ism_path_filename)
    
    # Remove temp workspace
    shutil.rmtree(work_path)
    
    return context.Response(body=str('Done'),
                            content_type='text/plain',
                            status_code=200)