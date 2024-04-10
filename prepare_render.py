import os
import shutil
import posixpath
import socket
import maya.cmds as cmds
import maya.mel as mel

# Description: Script for preparing and copying maya projects to the renderfarm directory
# 1. Verifies that file dependencies are set up correctly and that the user is in a lab that is part of the renderfarm. 
# 2. Copies the current maya file and all dependencies to the network render drive
# 3. Resolves all reference and texture paths in the copied files
# 4. Opens the copied maya file from the network render drive. 

#VERSION INFO:
# v1.0.1    02.04.2024   Initial Creation

__author__ = [ 'Nasheet Zaman' ]
__version__ = 'v1.0.1'

DEADLINE_LABS = ['DUDL1383','KNOY340']
USERNAME = os.getlogin()
RENDERFARM_DRIVE = 'J:'
RENDERFARM_USERS_DIR = posixpath.join(RENDERFARM_DRIVE,'CGT','RENDER','Assets')
RENDERFARM_USER_DIR = posixpath.join(RENDERFARM_USERS_DIR,USERNAME)
CURRENT_MAYA_FILE = cmds.file(q=True, sn=True)
CURRENT_PROJECT_FOLDER = cmds.workspace(fullName=True)
PROJECT_NAME = posixpath.basename(CURRENT_PROJECT_FOLDER)

# List all dependencies (references, textures, caches, etc) within the currently open maya file 
#
# Returns a dictionary in the format:
#    dependencies = {
#        'valid':set([ Paths to all dependencies that exist within the maya project folder and are linked properly ]),
#        'references':set([ Paths to referenced maya files ]),
#        'invalid':set([ Paths to files that exist, but are outside the maya project folder and/or linked improperly ]),
#        'nonexistant':set([ Paths to files that do not exist ])
#    }
def list_dependencies():
    
    all_files = {
        'valid':set([]),
        'references':set([]),
        'invalid':set([]),
        'nonexistant':set([])
    }
    
    maya_file = cmds.file(q=True, sn=True)
    maya_project = cmds.workspace(fullName=True)

    dependency_dirs = cmds.filePathEditor(query=True, listDirectories="")

    if dependency_dirs:
        for dependency_dir in dependency_dirs:
            dep_files = cmds.filePathEditor(query=True, listFiles=dependency_dir)
            for dep_file in dep_files:
                fullpath = posixpath.join(dependency_dir,dep_file)
            
                if os.path.exists(fullpath):
                    if fullpath.startswith(maya_project):
                        all_files['valid'].add(fullpath)
                    else:
                        all_files['invalid'].add(fullpath)
                else:
                    all_files['nonexistant'].add(fullpath)

    ref_files = cmds.file( maya_file, q=1, r=1 )
    
    if ref_files:
        for ref_file in ref_files:
            all_files['references'].add(ref_file)

    return all_files


#Return the "last modified" time of a given file. 
def _get_modified_time(filename):
    stat_info = os.stat(filename)
    return stat_info.st_mtime


#Copy a source file to a destination, skipping any newer files in the destination
def copyfile(src_file,dst_file,skip_newer=True):
    dst_dir = posixpath.dirname(dst_file)
    if not os.path.exists(dst_dir):
        os.makedirs(dst_dir)
    
    if os.path.exists(dst_file) :
        s_mtime = _get_modified_time(src_file)
        d_mtime = _get_modified_time(dst_file)
        if s_mtime <= d_mtime and skip_newer:
            #destination file is newer, nothing to copy
            print("Destination file is newer, skipping: ", src_file, "\t to \t", dst_file)
            return
        os.remove(dst_file)
        
    shutil.copy2(src_file,dst_file)
    print("COPIED: ",src_file,"\t to \t", dst_file)

#Resolves all file paths within the current maya file by replacing the path of the source project with the path of the destination project. 
def resolve_paths(source_project,dest_project):
    nodes = cmds.filePathEditor(query=True, listFiles="",ao=True)
    
    if not nodes:
        return
        
    for node in nodes:
        try:
            cmds.filePathEditor( node, replaceField="pathOnly", replaceString=(source_project,dest_project), replaceAll=True)
        except:
            cmds.error("Could not resolve: "+node)
            continue
            

# Creates the render image output directory if it doesn't already exist   
def create_output_dir():
    maya_file = cmds.file(q=True, sn=True)
    maya_project = cmds.workspace(shortName=True)
    
    #find the output directory in the project
    images_subdir= cmds.workspace(fre="images")
    if not images_subdir:
        images_subdir="images"
        
    images_dir = posixpath.join(maya_project, images_subdir)
    if not os.path.exists(images_dir):
        os.mkdir(images_dir)
        
# Alerts the user that the file is ready to render.       
def ready_to_render_dialog(filename):
    #cmds.confirmDialog(button="OK", message="SUCCESS: \n\n"+ filename + "\n\n is ready to send to the renderfarm. Hit the green button on the Deadline shelf to submit it.", title='Ready to Render')
    
    window = cmds.window( title="Ready to Render", widthHeight=(600, 150) )
    cmds.columnLayout( adjustableColumn=True, cal="center")
    cmds.text( label="SUCCESS: \n\n"+ filename + "\n\n is ready to send to the renderfarm. Hit the green button on the Deadline shelf to submit it.\n\n" )
    cmds.formLayout()
    cmds.button( width=100, label='OK', command=('cmds.deleteUI(\"' + window + '\", window=True)') )
    #cmds.setParent( '..' )
    cmds.showWindow( window )
 
    
# Collects the current maya file, all linked dependencies from the file, and the project folders
# Copies them to the network render drive 
# Resolves paths within the copied depencencies and the copied maya file
# Opens the copied maya file. 
def archive_and_copy_to_renderdir():
    
    #get all file dependencies
    dependencies = list_dependencies()      
    renderfarm_project = posixpath.join(RENDERFARM_USER_DIR,PROJECT_NAME)
 
    if dependencies['invalid'] or dependencies['nonexistant']:
        errormessage="File Path Errors Detected.\n"
        if dependencies['invalid']:
            errormessage+="\nThe following filepaths need to be fixed, as they point to files outside the project folder, "+ CURRENT_PROJECT_FOLDER + ". \n" + '\n'.join(dependencies['invalid'])
        if dependencies['nonexistant']:
            errormessage+="\nThe following filepaths do not exist:\n" + '\n'.join(dependencies['nonexistant'])

        cmds.confirmDialog( title='File Path Errors', message='File path errors found, see script editor for details.', button=['OK'], defaultButton='OK', cancelButton='OK', dismissString='OK' )
        mel.eval('FilePathEditor;')
        cmds.error(errormessage)
        return

    elif CURRENT_MAYA_FILE.startswith(RENDERFARM_USER_DIR):
        cmds.workspace(renderfarm_project,openWorkspace=True)
        create_output_dir()
        #print("SUCCESS: ", CURRENT_MAYA_FILE, " is ready to send to the renderfarm.")
        ready_to_render_dialog(CURRENT_MAYA_FILE)
        return

    #copy the maya workspace.mel and run it to set the proper directories in the new project
    workspace_mel = posixpath.join(CURRENT_PROJECT_FOLDER,'workspace.mel')
    if os.path.exists(workspace_mel):
        workspace_mel_copy = workspace_mel.replace(CURRENT_PROJECT_FOLDER,renderfarm_project)
        copyfile(workspace_mel,workspace_mel_copy)
        mel.eval('source "'+workspace_mel_copy+'"')
        
    #copy all the valid dependencies to the corresponding location in the new project folder
    for srcfile in dependencies['valid']:
        dstfile = srcfile.replace(CURRENT_PROJECT_FOLDER,renderfarm_project)
        copyfile(srcfile,dstfile)
    
    #copy the current maya file to the new project folder    
    render_filepath = CURRENT_MAYA_FILE.replace(CURRENT_PROJECT_FOLDER,renderfarm_project)
    copyfile( CURRENT_MAYA_FILE, render_filepath)
    print("Copied project",CURRENT_PROJECT_FOLDER," to ",renderfarm_project)
 
    #Set project to the copied project
    cmds.workspace(renderfarm_project,openWorkspace=True)
    
    #open and resolve filepaths in all of the referenced maya files. Save each new reference file in-place.
    for ref_file in dependencies['references']:
        ref_file_copy = ref_file.replace(CURRENT_PROJECT_FOLDER,renderfarm_project)
        cmds.file(ref_file_copy,open=True)
        resolve_paths(CURRENT_PROJECT_FOLDER,renderfarm_project) 
        print("Resolved all paths in reference file:", ref_file_copy)
        cmds.file(save=True)
        
    #open and resolve references in the parent file
    cmds.file(render_filepath,open=True,force=True)
    print("Opened Main File:", render_filepath)
    
    #unload references that were previously loaded (this prevents the script from trying to resolve paths that have already been resolved within the ref files)
    loaded_reference_files = [cmds.referenceQuery(file,referenceNode=True)  for file in cmds.file(reference=True, q=True) if cmds.referenceQuery(file, isLoaded=True)]
    for lr in loaded_reference_files:
        cmds.file(unloadReference=lr)
    
    #resolve file paths in the main maya file
    resolve_paths(CURRENT_PROJECT_FOLDER,renderfarm_project)
    
    #reload references that were previously loaded
    for lr in loaded_reference_files:
        cmds.file(loadReference=lr)
    
    #create the image output directory for rendering    
    create_output_dir()
    
    #Done
    cmds.file(save=True)
    ready_to_render_dialog(render_filepath)
    
    #print("SUCCESS: ", render_filepath, " is ready to send to the renderfarm.")


# Verifies that the user is sending the render from an approved lab, and then copies the necessary files onto the render network drive.   
def prepare_render(): 
    computername = socket.gethostname()
    computerlab = computername.split('PC')[0].replace('X-','')
    
    if not (computerlab in DEADLINE_LABS):
        cmds.error("The computer you are working on is not part of the render farm. Go to one of the following labs to submit a render job: " + " ".join(DEADLINE_LABS))
        return
    
    if not (os.path.exists(RENDERFARM_DRIVE)):
        cmds.error("Cannot find the %s/ network drive. " % RENDERFARM_DRIVE)
    
    archive_and_copy_to_renderdir()

prepare_render()