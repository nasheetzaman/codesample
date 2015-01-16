from maya import cmds
from maya import mel
import posixpath
import os
import re
import json
from pymel.all import *
from Pipeline_Tools.opp_utils import opp_helpers
import Pipeline_Tools.opp_utils.opp_prefs as opp_prefs
from Pipeline_Tools.opp_utils import opp_shot_assets
from Lighting_Tools import propagate_lightlinks
from Lighting_Tools import abxRenderLayers as abx #Courtesy of http://www.creativecrash.com/maya/script/abxrenderlayers

reload(abx)
reload(propagate_lightlinks)
#VERSION INFO:
# v1.0.1    3.10.2014   Initial Creation
# v1.0.2    3.10.2014   Correctly exports attribute overrides
# v1.0.3    6.10.2014   Fixes for lightlink filtering, skips camera nodes, handles some more complex attrs

__author__ = [ 'Nasheet Zaman' ]
__version__ = 'v1.0.3'


g_sandboxdir = opp_prefs.get_pref('sandbox_dir')
g_egnytedir = opp_prefs.get_pref('egnyte_dir')
g_lightrigdir= 'references_lookdev/lightrigs' 
g_lightrigname= 'lrig_main' # name of the main light rig group
g_large_assets=['prop_deck'] # For these assets, the script only permits lightlinking to the full group
standardMtls=set(['lambert1','particleCloud1']) # default materials that do not need to be propagated

g_lightrigdir_sandbox=os.path.join(g_sandboxdir, g_lightrigdir)
if not os.path.exists(g_lightrigdir_sandbox):
    message = g_lightrigdir_sandbox + " does not exist. Please create this directory in order to proceed."
    print "ERROR: ",message
    cmds.confirmDialog(title="ERROR", message=message)
    
class PropagateUI:
    """
    Build the Lighting Propagation UI
    """
    def __init__(self):
        self.egnytedir = g_egnytedir
        self.sandboxdir = g_sandboxdir
        self.sourcedir= self.sandboxdir
        self.jsonfile = ""
        self.configfile=""
        self.shot=''
        self.shots = []
        self.configfiles=[]
        self.layerList=None #TO DO: Allow selection of specific render layers
        self.importLights = True
        self.importLightlinks = False
        self.importRenderLayers = True
        self.windowName = 'PropagateUI'

        if cmds.window(self.windowName, q=True, exists=True):
            cmds.deleteUI(self.windowName)
        if cmds.windowPref(self.windowName, q=True, exists=True):
            cmds.windowPref(self.windowName, remove=True)

        self.win = cmds.window(self.windowName, title='Lighting Propagation UI %s' % (__version__), 
                               iconName='PropagateLightingUI', widthHeight=(650,280),
                               bgc=(0.23,0.23,0.23))

        self.mainlayout = cmds.formLayout("MainLayout", numberOfDivisions=100)
        self.propagate_button = cmds.button("propagateButton", label='Propagate', w=200, bgc=(0,.3,0), command=self.propagate_shot)
        self.sourcedir_chooser = cmds.radioButtonGrp(label="Source:", labelArray2=['Sandbox','Egnyte'],numberOfRadioButtons=2, select=1, cc=self.set_sourcedir)
        self.shotmenu = cmds.optionMenuGrp("shotmenu", label='Shot:', cc=self.set_shot)
        self.shotconfigmenu = cmds.optionMenuGrp("shotconfigmenu", label='Config:',  cc=self.set_config_file)
        self.jsonfile_label = cmds.text("json_lbl", label='')
        self.import_label = cmds.text("Import:", label='')
        self.importLightsCheckBox = cmds.checkBox( label='lights' , v=self.importLights)
        self.importLightlinksCheckBox = cmds.checkBox( label='lightlinks',v=self.importLightlinks )
        self.importRenderLayersCheckBox = cmds.checkBox( label='renderLayers',v= self.importRenderLayers )
        
        cmds.formLayout(self.mainlayout, edit=True, attachForm=
                                                        [
                                                        (self.sourcedir_chooser, "top", 10), 
                                                        (self.sourcedir_chooser, "left", 10), 
                                                        (self.shotmenu, "top", 50),
                                                        (self.shotmenu, "left", 50),
                                                        (self.shotconfigmenu, "top", 80), 
                                                        (self.shotconfigmenu, "left", 50),
                                                        (self.import_label, "top", 100), 
                                                        (self.import_label, "left", 150),
                                                        (self.importLightsCheckBox, "top", 120), 
                                                        (self.importLightsCheckBox, "left", 250),
                                                        (self.importLightlinksCheckBox, "top", 140), 
                                                        (self.importLightlinksCheckBox, "left", 250),
                                                        (self.importRenderLayersCheckBox, "top", 160), 
                                                        (self.importRenderLayersCheckBox, "left", 250),  
                                                        (self.jsonfile_label, "top", 190), 
                                                        (self.jsonfile_label, "left", 10),
                                                        (self.propagate_button, "top", 240), 
                                                        (self.propagate_button, "left", 200) 
                                                         ])

        cmds.setParent(self.win)
        self.update_shots_menu()
        cmds.showWindow(self.win)

    def set_sourcedir(self,*args):
        self.sourcedir= self.sandboxdir
        if cmds.radioButtonGrp(self.sourcedir_chooser,q=True,sl=True)==2:
            self.sourcedir=self.egnytedir
        self.update_shots_menu()
        
    def set_shot(self, *args):
        self.shot = cmds.optionMenuGrp(self.shotmenu, q=True, v=True)
        self.update_config_menu()
        
    def set_config_file(self, *args):
        self.configfile = cmds.optionMenuGrp(self.shotconfigmenu, q=True, v=True)
        self.jsonfile=''
        if self.configfile:
            self.jsonfile=os.path.join(self.sourcedir,g_lightrigdir, self.shot,self.configfile)
        cmds.text(self.jsonfile_label, e=True, label=self.jsonfile)

    def update_shots_menu(self, *args):
        '''refresh shots menu'''
        
        menuitems= self.get_shots()
        self.shot=''
        if menuitems:
            self.shot =menuitems[0]

        menu = self.shotmenu + "|OptionMenu"
        # clear menu items
        oldmenuitems = cmds.optionMenuGrp(self.shotmenu, q=True, ill=True)
        if oldmenuitems:
            cmds.deleteUI(oldmenuitems)
        if len(menuitems) > 0:
            for mi in menuitems:
                cmds.menuItem(l=mi, p=menu)

        shotitems =  cmds.optionMenuGrp(self.shotmenu, q=True, ill=True)

        if shotitems and self.shot:
            for i,v in enumerate(shotitems):
                menu_label = cmds.menuItem(v, q=True, l=True)
                if self.shot in menu_label:
                    cmds.optionMenuGrp(self.shotmenu, e=True, sl=(i+1))
                    break

        self.update_config_menu()
              
    def update_config_menu(self, *args):
         '''refresh config menu'''
         cmenuitems= self.get_config_files()
         self.configfile=''
         if cmenuitems:
             self.configfile =cmenuitems[-1]

         cmenu = self.shotconfigmenu + "|OptionMenu"
         # need to clear menu items
         coldmenuitems = cmds.optionMenuGrp(self.shotconfigmenu, q=True, ill=True)
         if coldmenuitems:
             cmds.deleteUI(coldmenuitems)
         if len(cmenuitems) > 0:
             for mi in cmenuitems:
                 cmds.menuItem(l=mi, p=cmenu)
         configitems =  cmds.optionMenuGrp(self.shotconfigmenu, q=True, ill=True)
         if configitems and self.configfile:
             for i,v in enumerate(configitems):
                 cmenu_label = cmds.menuItem(v, q=True, l=True)
                 if self.configfile in cmenu_label:
                     cmds.optionMenuGrp(self.shotconfigmenu, e=True, sl=(i+1))
                     break    
         self.set_config_file()  

    def get_shots(self, force=False):
        """get list of shots for the ui"""

        shotsdir = os.path.join(self.sourcedir, g_lightrigdir)
        shots=[]
        if os.path.exists(shotsdir):
            shots = os.listdir(shotsdir)
            
        shot_pat = re.compile("^\d\d_\d\d\d$")
        newshots = []
        for s in shots:
            s=str(s)
            m = shot_pat.search(s)
            if m:
                shotpath = os.path.join(self.sourcedir,g_lightrigdir, s)
                
                if os.path.exists(shotpath):
                    configs = os.listdir(shotpath)
                    hasConfigs=False
                    for c in configs:
                        if c.endswith('.json'):
                            hasConfigs = True
                    if hasConfigs:
                        newshots.append(s)

                
        newshots = sorted(newshots)
        self.shots = newshots
        return self.shots
    
    def get_config_files(self, force=False):
        """get list of config files for the ui"""
            
        files=[]
        configsdir = os.path.join(self.sourcedir, g_lightrigdir,self.shot)

        if os.path.exists(configsdir):
            files = os.listdir(configsdir)
        newfiles = []

        for f in files:
            f=str(f)
            if f.endswith('.json'):
                newfiles.append(f)
        newfiles = sorted(newfiles)
        self.configfiles = newfiles
        return self.configfiles
    
    
    def propagate_shot(self, *args):
        if not os.path.exists(self.jsonfile):
            cmds.confirmDialog(title="ERROR", message="json file not found: "+self.jsonfile)
            return
        
        self.importLights = cmds.checkBox(self.importLightsCheckBox ,q=True,v=True)
        self.importLightlinks = cmds.checkBox(self.importLightlinksCheckBox ,q=True,v=True)
        self.importRenderLayers = cmds.checkBox(self.importRenderLayersCheckBox ,q=True,v=True)
        
        importShotLightingConfig(self.jsonfile,lightrig=self.importLights,lightlinks=self.importLightlinks,renderlayers=self.importRenderLayers,layerList=self.layerList)


    def close_ui(self, *args):
        if cmds.window(self.windowName, q=True, exists=True):
            cmds.deleteUI(self.windowName)

def renameDeformerNodes(revert=False):
    """This method renames '*Deformed' nodes to work around an issue with node name clashes, as ref edits are usually stored
    using the short names. 

    :revert: If set to True, revert back to the original names. 
    """
    if revert:
        deformedNodes = cmds.ls("*Deformed___*",long=True)
        for n in deformedNodes:
            oldname = n.split('___')[0]
            newname= oldname.split('|')[-1]
            cmds.rename(n,newname)
    else:
        deformedNodes = cmds.ls("*Deformed",long=True)
        for n in deformedNodes:
            parts = n.split('|')
            shortName = parts[-1]
        
            if '___' in shortName:
                continue
            if len(parts)>1:
                parentName = '|'.join(parts[0:-1])
                directParent = parts[-2]
                if ':' in directParent:
                    ns = directParent.split(':')[0]
                    newName=shortName+'___'+'_'.join(parts).replace(ns+':','')
                    cmds.rename(n,newName)


def exportShotLightingConfig(basedir=g_sandboxdir,lightrig=True,lightlinks=True,renderlayers=True):
    """This method exports a config with the info needed to propagate lighting from one shot to another, including:
    - a maya file containing the light rig and any local shaders
    - a .json file containing lightlinks, renderlayers, and renderlayer overrides
    
    
    :basedir: The base directory to export the config 
    :lightrig: If true, export the light rig
    :lightlinks:  If true, export the lightlinks
    :renderlayers: If true, export the renderlayers
    """
    shotLightingDict={}
    p=opp_helpers.parse_current_filename()
    lrig_mainFile='%s_%s_lrig_main_v%s.ma' % (p['seq'],p['shot'],p['version'])
    mayadir=posixpath.join(basedir, "references_lookdev", "lightrigs", p['seq']+'_'+p['shot'])
    mayafile=posixpath.join(mayadir, lrig_mainFile)
    if not os.path.exists(mayadir):
        os.makedirs(mayadir)
    cmds.editRenderLayerGlobals( currentRenderLayer='defaultRenderLayer' )
    #Export light rigs
    if lightrig:
        print "Exporting lrig_main to: ",mayafile
        shotLightingDict['lrig_main']=exportLightRig(mayafile)
    #Export light links
    if lightlinks:
        print "Exporting lightlinks..."
        shotLightingDict['lightLinks']= exportLightLinks()
    #Export render layers
    if renderlayers:
        renameDeformerNodes() #Give the cache deformed nodes unique names to avoid name clashes (BIG HACK)
        print "Exporting renderLayers..."
        shotLightingDict['renderLayers'] = exportRenderLayers()
        renameDeformerNodes(revert=True) #Reset original names for cache deformed nodes (BIG HACK)

    jsonfile = posixpath.join(mayadir, lrig_mainFile.replace('.ma','.json'))
    opp_helpers.writejson(shotLightingDict,jsonfile)
    if not cmds.about(batch=True):
        cmds.confirmDialog(title="Export Complete!", message='Lighting Config File Created: \n\t'+jsonfile)
    print "Lighting Config File Created: ",jsonfile
    print "Export Complete!"


def enumerateAssets(assetList):
    """Return valid namespaces for assets so they can be queried in the scene. 
    Asset names in the assetlist might have '#'s in the name, and if so, this method replaces them with actual numbers.
    The enumerated asset names correspond with namespaces in the maya scene. 
    
    :assetList: A list containing all the assets
    
    return: A list of properly enumerated assets
    """
    newList =[]
    for a in assetList:
        newname = a
        if '###' in a:
            newname = a.replace('###','001')
        elif '##' in a:
            newname = a.replace('##','01')
        newList.append(newname)
    return newList
     
def importShotLightingConfig(jsonfile,lightrig=True,lightlinks=True,renderlayers=True,layerList=None):
    """This method uses a .json config file to re-build lightrigs, lightlinks, and renderlayers in the current scene
    
    :jsonfile: a config exported from another shot
    :lightrig: If true, propagate the light rig
    :lightlinks:  If true, propagate the lightlinks
    :renderlayers: If true, propagate the renderlayers
    """
    
    currentShot = ''
    sourceShot=''
    try:
        shotParse = opp_helpers.parse_current_filename()
        currentShot= shotParse['seq']+'_'+shotParse['shot']
    except:
        print "ERROR: Current maya file is not a valid shot file"
        return
    try:
        sourceShot = jsonfile.split('/')[-1].split('\\')[-1].split('_lrig_main_')[0]
    except:
        print "ERROR: Source json file does not follow the naming convention: ",jsonfile
        return
    print "Propagating Lighting Setup from ",sourceShot,"to",currentShot

    #The source shot may have assets that are not in the destination shot, and vice versa. 
    sourceAssets = set(enumerateAssets(opp_shot_assets.getAssetList(sourceShot)))
    destAssets = set(enumerateAssets(opp_shot_assets.getAssetList(currentShot)))
    skippedAssets = sourceAssets-destAssets
    newAssets = destAssets-sourceAssets

    messageFail = ''
    if skippedAssets:
        messageFail = "The following objects in the source shot but not in this shot. These will be skipped:\n"
        for f in skippedAssets:
            messageFail=messageFail+ '\t'+f + '\n'
    if newAssets:
        messageFail = "\nThe following assets are a part of this shot but were not in the source shot:\n"
        for f in newAssets:
            messageFail=messageFail+ '\t'+f + '\n'
    if messageFail:
        messageFail= "WARNING: "+ messageFail
        print messageFail
        if not cmds.about(batch=True):
            cmds.confirmDialog(title="WARNING", message=messageFail)
     
    cmds.editRenderLayerGlobals( currentRenderLayer='defaultRenderLayer' )
    
    #Import light rigs
    if lightrig:
        print "Importing lrig_main..."
        importLightRig(jsonfile,layerList,skippedAssets=skippedAssets)
    #Import light links
    if lightlinks:
        print "Importing and setting lightlinks..."
        importLightLinks(jsonfile,skippedAssets=skippedAssets)
    #Import render layers
    if renderlayers:
        renameDeformerNodes()        #Give the cache deformed nodes unique names to avoid name clashes 
        print "Importing renderLayers..."
        importRenderLayers(jsonfile,skippedAssets=skippedAssets)
        renameDeformerNodes(revert=True)        #Reset original names for cache deformed nodes 
    print "Import Complete!"
    
    
    if not cmds.about(batch=True):
        cmds.confirmDialog(title="Lighting Propagation UI", message='Setup Complete!')


def exportRenderLayers(jsonfile=''):
    """Export renderlayers and overrides to a .json file
        
    :jsonfile: file to write 
    
    returns: A dictionary of the members and overrides in each renderlayer
    """
    renderLayersAll = set(cmds.ls(type='renderLayer'))
    renderLayersRef = set(cmds.ls(type='renderLayer',rn=True))
    renderLayers = list(renderLayersAll - renderLayersRef)
    renderLayerDict = {}
    for renderLayer in renderLayers:
        if renderLayer == 'defaultRenderLayer':
            continue
        print "\tExporting renderLayer: ",renderLayer
        renderLayerDict[renderLayer]={}
        members = cmds.editRenderLayerMembers( renderLayer, query=True, fullNames=True )
        renderLayerDict[renderLayer]['members']=members
        #Select the layer
        cmds.editRenderLayerGlobals( currentRenderLayer=renderLayer )  
        editCommands = abx.exportRenderLayerEdits(renderLayer)
        renderLayerDict[renderLayer]['adjustments']=editCommands
            
    if jsonfile:        
        opp_helpers.writejson(renderLayerDict,jsonfile)
        
    return renderLayerDict

def importRenderLayers(jsonfile,layerList=None,skippedAssets=set([])):
    """Re-build the layers specified in the given .json file in the current maya scene
        
    :jsonfile: file to read
    :layerList: specific layers to build (not yet implemented)
    :skippedAssets: Assets that existed in the source shot, but not the destination shot
    """
    
    shotDict = opp_helpers.readjson(jsonfile)
    if not shotDict.has_key('renderLayers'):
        print "ERROR: No render layers specified in ",jsonfile
        return
    renderLayerDict = shotDict['renderLayers']
    failedSet=set([])
    if renderLayerDict:
        renderLayers = renderLayerDict.keys()
        badTypes = set([])
        for layer in renderLayers:
            if layerList:
                if not (layer in layerList):
                    continue
            #Create Render Layer
            renderLayer='defaultRenderLayer'
            if not (layer == 'defaultRenderLayer'):
                renderLayer = cmds.createRenderLayer(name=layer)
            if renderLayer=='defaultRenderLayer':
                continue
            print "\n\tCreating renderLayer: ",renderLayer
            cmds.editRenderLayerGlobals( currentRenderLayer=renderLayer )  
            #Add Members
            membersSet = set(renderLayerDict[layer]['members'])
            
            for m in list(membersSet):
                if not cmds.objExists(m):
                    #This means object ",m," existed in the parent shot, but not in this shot, so it can be skipped
                    topParent=m.split('|')[1]
                    objNamespace = topParent.replace('RNgroup','').split(':')[0]
                    failedSet.add(objNamespace)
                    membersSet.discard(m) #Make sure no ASSET_INFO nodes are included 
            members = list(membersSet)
            if not (layer=='defaultRenderLayer'):
                command = 'editRenderLayerMembers ' + renderLayer + " " + " ".join(members)
                mel.eval(command)
            #Add Adjustments
            adjustments =  list(set(renderLayerDict[layer]['adjustments']))
            
            abx.importRenderLayerAdjustments(renderLayer,adjustments,skippedAssets)

def exportLightRig(mayafile,lightRigName=g_lightrigname,jsonfile=''):
    """Export a maya file containing the light rig and any local shaders in the current lighting file. 
        
    :mayafile: long name of the file to export
    :lightRigName: Naming convention of the top-level light rig
    :jsonfile: json file for the shot config
    
    returns: short name of the maya file exported
    """
    
    try:
        #Get all materials that are local to the scene (not referenced in)
        mtls = list(set(cmds.ls(materials=True,rn=False))-set(cmds.ls(materials=True,rn=True))-standardMtls)
        selection = []
        for mtl in mtls:
            un = cmds.hyperShade(ldn=mtl)
            if un:
                for u in un:
                    if cmds.nodeType(u) == 'shadingEngine':
                        print "\tExporting material: ",mtl,u
                        selection.append(u)
                        selection.append(mtl)
        #Select the light rig
        selection.append(lightRigName)
        cmds.select(selection,r=True,ne=True)
    except:
        print "ERROR: ",lightRigName, " does not exist. Make sure your main light rig follows the naming convention"
        return
    cmds.file(mayafile, force=True, options="v=0", typ= "mayaAscii", pr=False, es=True)
    mayafile=mayafile.replace(g_egnytedir,'').replace(g_sandboxdir,'') #return a relative path
    return mayafile
    
def importLightRig(jsonfile,lightRigName=g_lightrigname,skippedAssets=set([])):
    """Import a specified light rig into the current lighting file. 
    
    :jsonfile: json file for the shot config        
    :lightRigName: Naming convention of the top-level light rig
    :skippedAssets: Assets that exist in the source file but not the destination file
    """
    shotDict = opp_helpers.readjson(jsonfile)
 
    if shotDict.has_key('lrig_main'):
        mayafile = jsonfile.replace('.json','.ma')
        cmds.file(mayafile, i=True, type="mayaAscii", options= "v=0" , pr = True)
        print "\tlrig_main imported from: ",mayafile
    else:
        print "ERROR: No light rig file specified in ",jsonfile
        return
    
    
def exportLightLinks(jsonfile=''):
    """Export lightlinks into a config file
    
    :jsonfile: json file for the shot config 
    
    returns: A dictionary containing information for re-building the lightlinks       
    """
    
    lights = cmds.ls(type='light',l=True)
    lightlinkDict = {}
    lightlinks = propagate_lightlinks.SaveLightLinksToFile()
    if lightlinks:
        lightlinkDict['melCommands']=lightlinks
    if jsonfile:
        opp_helpers.writejson(lightlinkDict,jsonfile)
        
    return lightlinkDict

def importLightLinks(jsonfile,skippedAssets=set([])):
    """Import and re-build lightlinks from a config file in the current scene
    
    :jsonfile: json file for the shot config
    :skippedAssets: Assets in the source file, but not the destination        
    """
    
    shotDict = opp_helpers.readjson(jsonfile)
    if not shotDict.has_key('lightLinks'):
        print "WARNING: No light links specified in ",jsonfile
        return
    lightlinkDict = shotDict['lightLinks']
    if not lightlinkDict.has_key('melCommands'):
        print "WARNING: No light link mel commands specified in ",jsonfile
        return
    filteredLightLinks = []
    for lightlinkCmd in lightlinkDict['melCommands']:
        assetName = lightlinkCmd.split('RNgroup')[0].split('|')[-1]
        splits = assetName.split('_')
        digit=''
        if len(splits)>1:
            digit = assetName.split('_')[-2]

        if digit.isdigit():
            assetName=assetName.replace(digit, len(digit)*'#')
        if not ((assetName in skippedAssets) or (assetName=='prop_deck')):
            if lightlinkCmd.startswith('}else'):
                filteredLightLinks.append('}')
            else:
                filteredLightLinks.append(lightlinkCmd)
    melCommand = '\n'.join(filteredLightLinks)
    mel.eval(melCommand)


    
