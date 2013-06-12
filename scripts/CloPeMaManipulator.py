#title           :CloPeMaManipulator.py
#description     :This class is an implementation of "Robot specific layer". The class implements Robot interface
#                 for robotic device used in CTU in project CloPeMa
#author          :Jan Sindler
#conact          :sidnljan@fel.cvut.cz
#date            :20130521
#version         :1.0
#usage           :cannot be used alone
#notes           :
#python_version  :2.7.3  
#==============================================================================

import roslib; roslib.load_manifest('contour_model_folding')
from RobInt import RobInt
import rospy
import cv
from cv_bridge import CvBridge, CvBridgeError
import logging
import sys
from visual_feedback_utils import Vector2D
import numpy as np
from sensor_msgs.msg import Image

# petrik script imports
import rospy, smach, smach_ros, math, copy, tf, PyKDL, os, shutil, numpy
from tf.transformations import quaternion_from_euler, quaternion_about_axis
from tf_conversions import posemath
from clopema_smach import *
from geometry_msgs.msg import *
from smach import State

# includes for pointcloud manipulation
from sensor_msgs.msg        import PointCloud2, PointField
from python_msg_conversions import pointclouds

class CloPeMaManipulator(RobInt):  

    lastImageIndex = 0
    graspPoints = None
    pcMap = None # point cloud map. Contain registred point cloud for measuring

    x_border = 0
    y_border = 0

    def liftUp(self, liftPoints):
        self.graspPoints = liftPoints

    def place(self, targPoints):
        N = 10
        target_point_real_a = self.map_to_real(targPoints[0], N)
        target_point_real_b = self.map_to_real(targPoints[1], N)
        grasp_point_real_a = self.map_to_real(self.graspPoints[0], N)
        grasp_point_real_b = self.map_to_real(self.graspPoints[1], N)
        
        diff_a = grasp_point_real_a - target_point_real_a
        line_a = (map(lambda a:a * 0.5, diff_a)) + target_point_real_a
        diff_b = grasp_point_real_b - target_point_real_b
        line_b = (map(lambda a:a * 0.5, diff_b)) + target_point_real_b
        
        sm = smach.Sequence(outcomes=['succeeded', 'preempted', 'aborted'], connector_outcome='succeeded')
        input_frame = '/xtion2_rgb_optical_frame'
        input_g1 = PyKDL.Frame()
        input_g2 = PyKDL.Frame()
        input_p1 = PyKDL.Frame()
        input_p2 = PyKDL.Frame()

        gp1 = grasp_point_real_a
        gp2 = grasp_point_real_b
        input_g1.p = PyKDL.Vector(gp1[0], gp1[1], gp1[2])
        input_g1.M = PyKDL.Rotation().RPY(math.pi / 2, 0, math.pi / 5)
        input_g2.p = PyKDL.Vector(gp2[0], gp2[1], gp2[2])
        input_g2.M = PyKDL.Rotation().RPY(math.pi / 2, 0, -math.pi / 5)
        input_p1.p = PyKDL.Vector(line_a[0], line_a[1], line_a[2])
        input_p2.p = PyKDL.Vector(line_b[0], line_b[1], line_b[2])

        tmp_pose = PoseStamped()
        tmp_pose.header.frame_id = input_frame
        tmp_pose.pose = posemath.toMsg(input_g1)
        sm.userdata.g1 = copy.deepcopy(tmp_pose)
        tmp_pose.pose = posemath.toMsg(input_g2)
        sm.userdata.g2 = copy.deepcopy(tmp_pose)
        tmp_pose.pose = posemath.toMsg(input_p1)
        sm.userdata.p1 = copy.deepcopy(tmp_pose)
        tmp_pose.pose = posemath.toMsg(input_p2)
        sm.userdata.p2 = copy.deepcopy(tmp_pose)

        sm.userdata.ik_link_1 = 'r1_ee'
        sm.userdata.ik_link_2 = 'r2_ee'
        sm.userdata.table_id = 't2'
        sm.userdata.offset_plus = 0.00
        sm.userdata.offset_minus = 0.1
        sm.userdata.rotation_angle_1 = 0
        sm.userdata.rotation_angle_2 = 0
        table_offset = 0.075
        
        br = tf.TransformBroadcaster()
        rospy.sleep(2.0)
        tmp = posemath.fromMsg(sm.userdata.g1.pose)
        br.sendTransform(tmp.p, tmp.M.GetQuaternion() , rospy.Time.now(), 'G1' , sm.userdata.g1.header.frame_id)
        tmp = posemath.fromMsg(sm.userdata.g2.pose)
        br.sendTransform(tmp.p, tmp.M.GetQuaternion() , rospy.Time.now(), 'G2' , sm.userdata.g1.header.frame_id)
        tmp = posemath.fromMsg(sm.userdata.p1.pose)
        br.sendTransform(tmp.p, tmp.M.GetQuaternion() , rospy.Time.now(), 'P1' , sm.userdata.g1.header.frame_id)
        tmp = posemath.fromMsg(sm.userdata.p2.pose)
        br.sendTransform(tmp.p, tmp.M.GetQuaternion() , rospy.Time.now(), 'P2' , sm.userdata.g1.header.frame_id)
        
        raw_input("Enter to continue")
        """
        sm_go_home = gensm_plan_vis_exec(PlanToHomeState(), output_keys=['trajectory']);
        with sm:
            smach.Sequence.add('GFOLD_FINAL', GFold2State(True, True, table_offset, 0.01))

        outcome = sm.execute()
"""
        #raw_input("Hit key to continue")

    ##  Load an image grabed by a camera.
    #
    #   @param index The index of image to be loaded
    #   @return The image loaded from a file        
    def getImageOfObsObject(self, index):
        takenImage = None
        self.lastImageIndex = index
        logging.info("Get image - waiting for msg")
        pcData = rospy.wait_for_message("/xtion2/depth_registered/points", PointCloud2)
        
        #convert it to format accepted by openCV
        logging.info("Get image - converting")
        arr = pointclouds.pointcloud2_to_array(pcData, split_rgb=self.has_rgb(pcData))

        if arr == None:
            rospy.logerr(rospy.get_name() + ": Failed to convert PoinCloud to numpy array!")
            return False

        if self.has_fields(['x', 'y', 'z'], arr):
            xyz = np.zeros(list(arr.shape) + [3], dtype=np.float32)
            xyz[..., 0] = arr['x']
            xyz[..., 1] = arr['y']
            xyz[..., 2] = arr['z']
            self.pcMap = xyz

        if self.has_fields(['r', 'g', 'b'], arr):
            rgb = np.zeros(list(arr.shape) + [3], dtype=np.uint8)
            rgb[..., 0] = arr['b']
            rgb[..., 1] = arr['g']
            rgb[..., 2] = arr['r']
            
        takenImage = cv.fromarray(rgb)
        
        logging.debug("Get image - completed")
        return takenImage
        
    ## Compute and return homography between side and top view
    #
    #  It takes the current view into one directly above the table. Correspondence 
    #    between points was made by a hand.
    #  @return 3x3 homography matrix
    def get_homography(self):
        H = cv.CreateMat(3, 3, cv.CV_32FC1)
        cv.Set(H, 0.0)
        H[0, 0] = 1
        H[1, 1] = 1
        H[2, 2] = 1
        return H 
        
        
# Private functions
    def has_rgb(self, msg):
        return "rgb" in [pf.name for pf in msg.fields]
        
    def has_fields(self, fields, arr):
        for field in fields:
            if not field in arr.dtype.names:
                return False

        return True
        
    """
    Map pixel position into 3D point, find the closest non-nan value
    """
    def map_to_real(self, img_point, N):
        X, Y = np.meshgrid(np.arange(-N, N), np.arange(-N, N))
        xyv = []
        for (x, y), value in np.ndenumerate(X):
            v = (X[x, y], Y[x, y])
            xyv.append(v)
            
        xyv.sort(key=lambda i:(i[0] ** 2 + i[1] ** 2))
        for v in xyv:
            p = (img_point[0] + v[0],
                 img_point[1] + v[1])
            pr = self.pcMap[p]
            if not math.isnan(pr[0]):
                if not math.isnan(pr[1]):
                    return pr
        return None
